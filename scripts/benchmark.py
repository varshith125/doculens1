"""Measure real OCR and full ASGI API latency on a generated, fictional fixture."""

import argparse
import io
import json
import platform
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path

import numpy as np
import psutil
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from generate_fixture import specimen_image

from app.core.config import Settings
from app.main import create_app
from app.services.ocr import OCRService


def percentile(values, fraction):
    return round(float(np.percentile(values, fraction)), 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("docs/benchmark.json"))
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("Use at least three runs.")
    data = io.BytesIO()
    specimen_image().save(data, "JPEG", quality=95)
    payload = data.getvalue()
    engine = OCRService()
    app = create_app(Settings(), engine)
    cold_start = time.perf_counter()
    samples = []

    def scan_once():
        # Individual cookie jars exercise session ownership under concurrent requests.
        with context_client(app) as client:
            client.post("/api/v1/session")
            started = time.perf_counter()
            response = client.post(
                "/api/v1/scans",
                files={"front": ("specimen.jpg", payload, "image/jpeg")},
            )
            response.raise_for_status()
            scan_id = response.json()["scan_id"]
            while time.perf_counter() - started < 120:
                status = client.get(f"/api/v1/scans/{scan_id}").json()
                if status["status"] == "failed":
                    raise RuntimeError(status["error"])
                if status["status"] == "completed":
                    break
                time.sleep(0.02)
            else:
                raise RuntimeError("Benchmark scan timed out")
            elapsed = (time.perf_counter() - started) * 1000
            result = status["result"]
            client.delete(f"/api/v1/scans/{scan_id}")
            return elapsed, result

    with TestClient(app):
        cold_ms = (time.perf_counter() - cold_start) * 1000
        if not engine.ready:
            raise RuntimeError("OCR startup failed")
        result = None
        for index in range(args.runs):
            elapsed, result = scan_once()
            samples.append({"request_ms": round(elapsed, 2), **result["timings_ms"]})
            print(f"Scan {index + 1}/{args.runs}: {elapsed:.0f} ms", flush=True)
        if result is None:
            raise RuntimeError("No benchmark scans completed")
        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent = list(pool.map(lambda _: scan_once()[0], range(4)))
        report = {
            "date": "2026-10-26",
            "fixture": "Generated 1400x940 JPEG, public fictional ICAO sample; no real IDs",
            "method": "In-process ASGI API; real RapidOCR/ONNX CPU; 20 ms polling; one OCR worker; no network latency",
            "hardware": {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "logical_cpus": psutil.cpu_count(),
                "ram_gb": round(psutil.virtual_memory().total / 1024**3, 1),
            },
            "versions": {
                name: version(name)
                for name in [
                    "rapidocr",
                    "onnxruntime",
                    "opencv-python-headless",
                    "fastapi",
                ]
            },
            "cold_model_start_ms": round(cold_ms, 2),
            "runs": args.runs,
            "p50_ms": percentile([s["request_ms"] for s in samples], 50),
            "p95_ms": percentile([s["request_ms"] for s in samples], 95),
            "mean_ms": round(statistics.mean(s["request_ms"] for s in samples), 2),
            "process_rss_mb": round(psutil.Process().memory_info().rss / 1024**2, 2),
            "two_client_four_requests_ms": [round(value, 2) for value in concurrent],
            "samples": samples,
            "observed": {
                "ocr_lines": len(result["ocr_lines"]),
                "mrz_detected": result["mrz"]["detected"], # type: ignore
                "mrz_checksum_valid": result["mrz"]["checksum_valid"],
                "field_names": list(result["fields"]),
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in [
                        "cold_model_start_ms",
                        "p50_ms",
                        "p95_ms",
                        "process_rss_mb",
                        "observed",
                    ]
                },
                indent=2,
            )
        )


@contextmanager
def context_client(app):
    """Share the already-running application lifespan with a separate cookie jar."""
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()


if __name__ == "__main__":
    main()
