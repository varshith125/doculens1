import time

import cv2

from app.core.store import CapacityError, ScanJob, ScanStore
from app.extractors.field_extractor import extract_fields
from app.schemas.models import ScanOptions, ScanResult
from app.services.imaging import ImageValidationError, decode_image, encode_jpeg, process_image
from app.services.ocr import OCRService, OCRUnavailableError


class Cancelled(Exception):
    pass


def run_scan(
    job: ScanJob,
    uploads: dict[str, bytes],
    options: ScanOptions,
    store: ScanStore,
    ocr: OCRService,
) -> None:
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
        all_lines = []
        images = []
        stored_images = {}
        warnings = []
        if options.language == "arabic":
            warnings.append(
                "Arabic recognition is experimental. Review every Arabic and Latin value against the original; model confidence does not guarantee accuracy."
            )
        for side, data in uploads.items():
            stage("detecting_document")
            tick = time.perf_counter()
            original = decode_image(data)
            measure("image_decode", tick)
            stage("correcting_alignment")
            tick = time.perf_counter()
            side_options = getattr(options, side)
            processed = process_image(original, side=side, options=side_options)
            measure("detection_and_correction", tick)
            stage("reading_text")
            tick = time.perf_counter()
            corrected, lines, rotation = ocr.read_oriented(
                processed.corrected,
                side=side,
                language=options.language,
                auto_rotate=side_options.rotation == 0,
            )
            measure("ocr", tick)
            metadata = processed.metadata
            metadata.width = int(corrected.shape[1])
            metadata.height = int(corrected.shape[0])
            metadata.rotation = (metadata.rotation + rotation) % 360
            metadata.original_url = (
                f"/api/v1/scans/{job.scan_id}/image?side={side}&variant=original"
            )
            metadata.corrected_url = (
                f"/api/v1/scans/{job.scan_id}/image?side={side}&variant=corrected"
            )
            images.append(metadata)
            warnings.extend(metadata.warnings)
            all_lines.extend(lines)
            tick = time.perf_counter()
            stored_images[(side, "original")] = encode_jpeg(processed.original)
            stored_images[(side, "corrected")] = encode_jpeg(corrected)
            measure("image_encoding", tick)
        stage("validating_fields")
        tick = time.perf_counter()
        extracted = extract_fields(all_lines, date_order=options.date_order)
        warnings.extend(extracted.pop("warnings", []))
        if not all_lines:
            warnings.append(
                "No readable text was found. Try a sharper image with even lighting or adjust the crop."
            )
        warnings.append(
            "Checks validate readings and formats only; they do not establish document authenticity."
        )
        measure("field_extraction", tick)
        stage("preparing_results")
        measure("processing_total", started)
        timings["queue_wait"] = round(max(0, started_monotonic - job.created) * 1000, 2)
        timings["total"] = round((time.monotonic() - job.created) * 1000, 2)
        result = ScanResult(
            scan_id=job.scan_id,
            **extracted,
            images=images,
            ocr_lines=all_lines,
            warnings=list(dict.fromkeys(warnings)),
            timings_ms=timings,
        )
        store.complete(job, result, stored_images)
    except Cancelled:
        return
    except (ImageValidationError, OCRUnavailableError, CapacityError) as exc:
        with store.lock:
            if not job.cancelled.is_set():
                job.status = job.stage = "failed"
                job.error = str(exc)
    except Exception:
        with store.lock:
            if not job.cancelled.is_set():
                job.status = job.stage = "failed"
                job.error = "The document could not be processed. Try another image or restart the local scanner."
    finally:
        uploads.clear()
