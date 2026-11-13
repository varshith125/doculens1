"""One scan, end to end: prepare each side, read its text, then extract fields."""

import logging
import time

import cv2
import numpy as np

from app.core.config import Settings, get_settings
from app.core.store import CapacityError, ScanJob, ScanStore
from app.extractors.field_extractor import extract_fields
from app.extractors.label_matcher import cached_label_matches
from app.schemas.models import ImageResult, OCRLine, ScanOptions, ScanResult, Side
from app.services.imaging import (
    ImageValidationError,
    brighten_if_dark,
    decode_image,
    encode_jpeg,
    process_image,
    rotate_image,
)
from app.services.mrz_recovery import recover_mrz
from app.services.ocr import OCRCancelled, OCRService, OCRUnavailableError
from app.services.output import prepare_output

logger = logging.getLogger(__name__)

SIDES: tuple[Side, ...] = ("front", "back")
# Fewer lines than this after an automatic crop means the crop is doubted.
MIN_CROPPED_LINES = 6
WHOLE_PAGE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


class Cancelled(Exception):
    pass


def crop_cuts_text(lines: list[OCRLine], shape: tuple[int, ...]) -> bool:
    """True when several text lines start or end right at the image edge.

    A document's own margin keeps printed text away from its edges, so lines
    touching the left or right border were most likely sliced by the crop.
    """
    width = shape[1]
    margin = max(3.0, 0.012 * width)
    touching = sum(
        1 for line in lines
        if min(p[0] for p in line.bounding_box) <= margin
        or max(p[0] for p in line.bounding_box) >= width - margin
    )
    return touching >= max(2, round(0.2 * len(lines)))


def _text_amount(lines: list[OCRLine]) -> int:
    return sum(len(line.text) for line in lines)


@cached_label_matches()
def run_scan(
    job: ScanJob,
    uploads: dict[str, bytes],
    options: ScanOptions,
    store: ScanStore,
    ocr: OCRService,
    config: Settings | None = None,
) -> None:
    config = config or get_settings()
    started = time.perf_counter()
    started_monotonic = time.monotonic()
    timings: dict[str, float] = {}

    def stage(value: str) -> None:
        with store.lock:
            if job.cancelled.is_set():
                raise Cancelled
            job.status = "processing"
            job.stage = value

    def measure(name: str, since: float) -> None:
        timings[name] = round(timings.get(name, 0) + (time.perf_counter() - since) * 1000, 2)

    try:
        cv2.setNumThreads(2)
        images: dict[Side, ImageResult] = {}
        pages: dict[Side, np.ndarray] = {}
        uncropped: dict[Side, np.ndarray] = {}
        stored_images: dict[tuple[str, str], bytes] = {}
        warnings: list[str] = []
        if options.language == "arabic":
            warnings.append(
                "Arabic recognition is experimental. Review every Arabic and Latin value against the original; model confidence does not guarantee accuracy."
            )

        for side in SIDES:
            stage("detecting_document")
            data = uploads.get(side)
            if data is None:
                continue
            tick = time.perf_counter()
            original = decode_image(data)
            measure("image_decode", tick)

            stage("correcting_alignment")
            tick = time.perf_counter()
            side_options = getattr(options, side)
            processed = process_image(original, side=side, options=side_options)
            measure("detection_and_correction", tick)

            metadata = processed.metadata
            brightened = brighten_if_dark(processed.corrected, (metadata.quality or {}).get("brightness", 128.0))
            if brightened is not None:
                processed.corrected = brightened
                metadata.warnings.append("Adaptive gamma brightening applied for low-light document.")
            pages[side] = processed.corrected
            if metadata.crop_applied and side_options.corners is None:
                # Kept only to recover when an automatic crop removed the text.
                uncropped[side] = rotate_image(processed.original, side_options.rotation)
            images[side] = metadata
            warnings.extend(metadata.warnings)

            tick = time.perf_counter()
            if data.startswith(b"%PDF-"):
                # The browser already shows an uploaded photo; only a PDF page,
                # which it cannot render, is sent back.
                stored_images[(side, "original")] = encode_jpeg(processed.original)
            stored_images[(side, "corrected")] = encode_jpeg(processed.corrected)
            measure("image_encoding", tick)

        all_lines: list[OCRLine] = []
        for side, page in pages.items():
            stage("reading_text")
            tick = time.perf_counter()
            read, lines, rotation, used_whole = _read_side(
                ocr, page, uncropped.get(side), side, options.language, job,
            )
            metadata = images[side]
            if used_whole:
                metadata.crop_applied = False
                metadata.corners = [corner.copy() for corner in WHOLE_PAGE]
                note = "The automatic crop cut off text, so the whole image was read instead."
                metadata.warnings.append(note)
                warnings.append(note)
            metadata.width, metadata.height = int(read.shape[1]), int(read.shape[0])
            metadata.rotation = (metadata.rotation + rotation) % 360
            if read is not page:
                stored_images[(side, "corrected")] = encode_jpeg(read)

            lines = recover_mrz(
                lines, read, side, ocr=ocr, config=config, language=options.language,
                cancelled=job.cancelled, measure=measure,
            )
            measure("ocr", tick)
            all_lines.extend(lines)

        stage("validating_fields")
        tick = time.perf_counter()
        extracted = prepare_output(extract_fields(all_lines, date_order=options.date_order))
        if not all_lines:
            warnings.append(
                "No readable text was found. Try a sharper image with even lighting or adjust the crop."
            )
        measure("field_extraction", tick)

        warnings.extend(extracted.pop("warnings", []))
        warnings.append(
            "Checks validate readings and formats only; they do not establish document authenticity."
        )
        stage("preparing_results")
        measure("processing_total", started)
        timings["queue_wait"] = round(max(0, started_monotonic - job.created) * 1000, 2)
        timings["total"] = round((time.monotonic() - job.created) * 1000, 2)
        result = ScanResult(
            scan_id=job.scan_id,
            **extracted,
            images=list(images.values()),
            ocr_lines=all_lines,
            warnings=list(dict.fromkeys(warnings)),
            timings_ms=timings,
        )
        store.complete(job, result, stored_images)
    except (Cancelled, OCRCancelled):
        return
    except (ImageValidationError, OCRUnavailableError, CapacityError) as exc:
        _fail(job, store, str(exc))
    except Exception:
        logger.exception("Unexpected scan failure at stage %s", job.stage)
        _fail(job, store, "The document could not be processed. Try another image or restart the local scanner.")
    finally:
        uploads.clear()


def _read_side(
    ocr: OCRService, page: np.ndarray, uncropped: np.ndarray | None, side: Side,
    language: str, job: ScanJob,
) -> tuple[np.ndarray, list[OCRLine], int, bool]:
    """Read one side; fall back to the uncropped image when the crop looks wrong.

    Manual rotation is already applied. OCR still needs upright geometry to
    associate captions, values and adjacent MRZ rows, so auto-rotation stays on.
    """
    read, lines, rotation = ocr.read_oriented(
        page, side=side, language=language, auto_rotate=True, cancelled=job.cancelled,
    )
    doubtful = len(lines) < MIN_CROPPED_LINES or crop_cuts_text(lines, read.shape)
    if uncropped is None or not doubtful or job.cancelled.is_set():
        return read, lines, rotation, False
    whole, whole_lines, whole_rotation = ocr.read_oriented(
        uncropped, side=side, language=language, auto_rotate=True, cancelled=job.cancelled,
    )
    if _text_amount(whole_lines) > _text_amount(lines):
        return whole, whole_lines, whole_rotation, True
    return read, lines, rotation, False


def _fail(job: ScanJob, store: ScanStore, message: str) -> None:
    with store.lock:
        if not job.cancelled.is_set():
            job.status = job.stage = "failed"
            job.error = message
            job.completed_at = time.monotonic()
