import asyncio
import contextlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import anyio
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.formparsers import MultiPartParser
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import Settings, get_settings
from app.core.middleware import RequestGuard
from app.core.security import COOKIE_NAME, SESSION_LIFETIME, Sessions, require_owner
from app.core.store import CapacityError, ScanStore
from app.schemas.models import HealthResponse, JobResponse, ScanOptions
from app.services.ocr import OCRService
from app.services.pipeline import run_scan

Owner = Annotated[str, Depends(require_owner)]


def create_app(settings: Settings | None = None, ocr: OCRService | None = None) -> FastAPI:
    config = settings or get_settings()
    engine = ocr or OCRService(
        arabic_model_path=config.arabic_model_path,
        arabic_dictionary_path=config.arabic_dictionary_path,
    )
    store = ScanStore(
        config.retention_seconds, config.max_active_scans, config.max_storage_mb * 1024**2
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.executor = ThreadPoolExecutor(
            max_workers=config.workers, thread_name_prefix="scan"
        )
        try:
            await anyio.to_thread.run_sync(engine.warmup)
        except Exception:
            # Readiness exposes model failure without exposing internal errors or filesystem paths.
            pass

        async def cleanup():
            while True:
                await asyncio.sleep(min(15, config.retention_seconds))
                store.prune()

        task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            store.clear()
            application.state.executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(
        title="DocuLens", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.sessions = Sessions()
    app.state.store = store
    app.state.ocr = engine
    app.state.config = config
    # Bounded uploads remain in RAM; no original identity files are spooled to disk.
    MultiPartParser.spool_max_size = (config.max_upload_mb * 2 + 1) * 1024**2
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(
        RequestGuard,
        max_bytes=(config.max_upload_mb * 2 + 1) * 1024**2,
        allowed_origins=config.allowed_origins,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return JSONResponse({"detail": "Invalid request. Check the files and scan options."}, 422)

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health():
        return {
            "status": "ok" if engine.ready else "degraded",
            "ocr_ready": engine.ready,
            "languages": engine.languages,
            "retention_seconds": config.retention_seconds,
            "max_upload_mb": config.max_upload_mb,
            "version": "1.0.0",
        }

    @app.post("/api/v1/session")
    def session(request: Request, response: Response):
        token = request.cookies.get(COOKIE_NAME)
        if not app.state.sessions.owner(token):
            token = app.state.sessions.issue()
            response.set_cookie(
                COOKIE_NAME,
                token,
                max_age=SESSION_LIFETIME,
                httponly=True,
                secure=config.cookie_secure,
                samesite="strict",
                path="/api/v1",
            )
        return {"status": "ready", "retention_seconds": config.retention_seconds}

    @app.post("/api/v1/scans", status_code=202, response_model=JobResponse)
    async def scan(
        owner: Owner,
        front: Annotated[UploadFile, File()],
        back: Annotated[UploadFile | None, File()] = None,
        options: Annotated[str, Form()] = "{}",
    ):
        if not engine.ready:
            raise HTTPException(
                503,
                "OCR is unavailable. Check the local model installation and restart the backend.",
            )
        try:
            parsed = ScanOptions.model_validate_json(options)
        except (ValidationError, ValueError, json.JSONDecodeError):
            raise HTTPException(422, "Invalid scan options.") from None
        if parsed.language not in engine.languages:
            raise HTTPException(422, "The selected OCR language model is not installed.")
        uploads = {}
        try:
            for side, file in (("front", front), ("back", back)):
                if file is None:
                    continue
                data = await file.read(config.max_upload_mb * 1024**2 + 1)
                if len(data) > config.max_upload_mb * 1024**2:
                    raise HTTPException(
                        413, f"Each image must be {config.max_upload_mb} MB or smaller."
                    )
                is_jpeg = data.startswith(b"\xff\xd8\xff")
                is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
                is_webp = data.startswith(b"RIFF") and data[8:12] == b"WEBP"
                if not (is_jpeg or is_png or is_webp):
                    raise HTTPException(415, "Upload a valid JPEG, PNG, or WebP image.")
                uploads[side] = data
            try:
                job = store.create(owner)
            except CapacityError as exc:
                raise HTTPException(429, str(exc)) from None
            app.state.executor.submit(run_scan, job, uploads, parsed, store, engine)
            return {"scan_id": job.scan_id, "status": job.status, "stage": job.stage}
        finally:
            await front.close()
            if back:
                await back.close()

    def owned_job(scan_id: str, owner: str):
        job = store.get(scan_id, owner)
        if not job:
            raise HTTPException(404, "Scan not found or expired. Upload the document again.")
        return job

    @app.get("/api/v1/scans/{scan_id}", response_model=JobResponse)
    def scan_status(scan_id: str, owner: Owner):
        with store.lock:
            job = owned_job(scan_id, owner)
            return {
                "scan_id": job.scan_id,
                "status": job.status,
                "stage": job.stage,
                "result": job.result.model_dump() if job.result else None,
                "error": job.error,
            }

    @app.get("/api/v1/scans/{scan_id}/image")
    def scan_image(
        scan_id: str,
        owner: Owner,
        side: Literal["front", "back"] = "front",
        variant: Literal["original", "corrected"] = "corrected",
    ):
        with store.lock:
            job = owned_job(scan_id, owner)
            image = job.images.get((side, variant))
            if image is None:
                raise HTTPException(404, "Image is not available.")
            return Response(content=image, media_type="image/jpeg")

    @app.delete("/api/v1/scans/{scan_id}", status_code=204)
    def delete_scan(scan_id: str, owner: Owner):
        if not store.delete(scan_id, owner):
            raise HTTPException(404, "Scan not found or expired.")
        return Response(status_code=204)

    # A production build can be served on the same origin without a second server.
    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
