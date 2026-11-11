import logging
import time

import cv2
import numpy as np

from app.core.config import Settings, get_settings
from app.core.store import CapacityError, ScanJob, ScanStore
from app.extractors.field_extractor import extract_fields
from app.extractors.label_matcher import cached_label_matches
from app.schemas.models import ScanOptions, ScanResult
from app.services.imaging import (
    ImageValidationError,
    decode_image,
    encode_jpeg,
    process_image,
    rotate_image,
)
from app.services.ocr import OCRCancelled, OCRService, OCRUnavailableError
from app.services.output import prepare_output

logger = logging.getLogger(__name__)


# Fewer lines than this after an automatic crop means the crop is doubted.
MIN_CROPPED_LINES = 6


class Cancelled(Exception):
    pass


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
        all_lines: list = []
        images = []
        stored_images = {}
        corrected_images: dict[str, object] = {}
        uncropped: dict[str, object] = {}
        warnings: list[str] = []
        if options.language == "arabic":
            warnings.append(
                "Arabic recognition is experimental. Review every Arabic and Latin value against the original; model confidence does not guarantee accuracy."
            )

        # ── Phase 1: Image preprocessing (always runs) ──────────────
        for side in ("front", "back"):
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

            # Preserve source pixels at document scale. Recognition already resizes
            # individual text crops; page-wide enlargement/sharpening can erase
            # strokes in small captions and MRZ characters.
            # Adaptive illumination normalization for dark or unevenly lit documents
            q = metadata.quality or {}
            if q.get("brightness", 128.0) < 85.0:
                gamma = max(0.4, q["brightness"] / 120.0)
                table = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)]).astype("uint8")
                processed.corrected = cv2.LUT(processed.corrected, table)
                metadata.warnings.append("Adaptive gamma brightening applied for low-light document.")
            # A bright page is not evidence of glare. Contrast recovery remains
            # conditional on poor OCR or measured darkness/low contrast.

            # Store the corrected image for subsequent OCR and recovery stages
            corrected_images[side] = processed.corrected
            if metadata.crop_applied and side_options.corners is None:
                # Kept only to recover when an automatic crop removed the text.
                uncropped[side] = rotate_image(processed.original, side_options.rotation)

            metadata.original_url = (
                f"/api/v1/scans/{job.scan_id}/image?side={side}&variant=original"
            )
            metadata.corrected_url = (
                f"/api/v1/scans/{job.scan_id}/image?side={side}&variant=corrected"
            )
            images.append(metadata)
            warnings.extend(metadata.warnings)

            tick = time.perf_counter()
            stored_images[(side, "original")] = encode_jpeg(processed.original)
            stored_images[(side, "corrected")] = encode_jpeg(processed.corrected)
            measure("image_encoding", tick)

        # ── Phase 2: Local OCR Extraction ──
        for side in ("front", "back"):
            if side not in corrected_images:
                continue
            stage("reading_text")
            tick = time.perf_counter()
            corrected, lines, rotation = ocr.read_oriented(
                corrected_images[side],
                side=side,
                language=options.language,
                # Manual rotation is already applied. OCR still needs upright
                # geometry to associate captions, values, and adjacent MRZ rows.
                auto_rotate=True,
                cancelled=job.cancelled,
            )
            if side in uncropped and len(lines) < MIN_CROPPED_LINES and not job.cancelled.is_set():
                # An estimated crop that leaves almost no text probably missed the
                # document. Read the whole image and keep whichever shows more text.
                whole, whole_lines, whole_rotation = ocr.read_oriented(
                    uncropped[side], side=side, language=options.language,
                    auto_rotate=True, cancelled=job.cancelled,
                )
                if sum(len(row.text) for row in whole_lines) > sum(len(row.text) for row in lines):
                    corrected, lines, rotation = whole, whole_lines, whole_rotation
                    for meta in images:
                        if meta.side == side:
                            meta.crop_applied = False
                            meta.corners = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
                            meta.warnings.append(
                                "The automatic crop left almost no readable text, so the whole image was read instead."
                            )
                            warnings.append(meta.warnings[-1])
            uncropped.pop(side, None)
            # Update metadata with OCR-corrected dimensions/rotation
            for meta in images:
                if meta.original_url and f"side={side}" in meta.original_url:
                    meta.width = int(corrected.shape[1])
                    meta.height = int(corrected.shape[0])
                    meta.rotation = (meta.rotation + rotation) % 360
            # Re-encode if OCR rotated the image
            if corrected is not corrected_images[side]:
                stored_images[(side, "corrected")] = encode_jpeg(corrected)
            corrected_images[side] = corrected

            # Retry an observed MRZ only when its checksum needs recovery.
            from app.extractors.mrz_parser import detect_mrz
            from app.services.imaging import apply_clahe
            # A cheap second opinion first: Tesseract rereads only the MRZ rows.
            mrz_check, _ = detect_mrz([line for line in lines if line.side == side])
            tesseract = getattr(ocr, "tesseract", None)
            if (
                config.enable_tesseract_backup
                and mrz_check.detected
                and mrz_check.checksum_valid is not True
                and not job.cancelled.is_set()
                and tesseract is not None
                and tesseract.is_available()
            ):
                tess_mrz_started = time.perf_counter()
                try:
                    h, w = corrected.shape[:2]
                    mrz_lines_existing = [
                        line for line in lines
                        if line.side == side and ("<" in line.text or "<<" in line.text) and len(line.text.replace(" ", "")) >= 20
                    ]
                    if mrz_lines_existing:
                        min_y = max(0, int(min(min(pt[1] for pt in l.bounding_box) for l in mrz_lines_existing)) - 6)
                        max_y = min(h, int(max(max(pt[1] for pt in l.bounding_box) for l in mrz_lines_existing)) + 6)
                        min_x = max(0, int(min(min(pt[0] for pt in l.bounding_box) for l in mrz_lines_existing)) - 6)
                        max_x = min(w, int(max(max(pt[0] for pt in l.bounding_box) for l in mrz_lines_existing)) + 6)
                        mrz_band_crop = corrected[min_y:max_y, min_x:max_x]
                        tess_mrz_rows = tesseract.recognize_mrz_block(mrz_band_crop, psm=6)
                        if tess_mrz_rows:
                            from app.schemas.models import OCRLine, OCRObservation
                            num_rows = len(tess_mrz_rows)
                            row_h = (max_y - min_y) / max(1, num_rows)
                            tess_ocr_lines = []
                            for idx, (t_text, t_conf) in enumerate(tess_mrz_rows):
                                r_top = min_y + idx * row_h
                                r_bot = r_top + row_h
                                box = [
                                    [float(min_x), float(r_top)],
                                    [float(max_x), float(r_top)],
                                    [float(max_x), float(r_bot)],
                                    [float(min_x), float(r_bot)],
                                ]
                                tess_ocr_lines.append(
                                    OCRLine(
                                        text=t_text,
                                        confidence=t_conf,
                                        bounding_box=box,
                                        side=side,
                                        observations=[
                                            OCRObservation(
                                                text=t_text,
                                                confidence=t_conf,
                                                method="Tesseract fallback: MRZ block",
                                            )
                                        ],
                                        review_required=True,
                                        recognition_note="MRZ recovered by Tesseract backup engine.",
                                    )
                                )
                            tess_mrz, _ = detect_mrz(tess_ocr_lines)
                            tess_valid_count = sum(1 for v in tess_mrz.checks.values() if v is True)
                            check_valid_count = sum(1 for v in mrz_check.checks.values() if v is True)
                            if tess_mrz.checksum_valid or (
                                tess_mrz.detected and tess_valid_count > check_valid_count
                            ):
                                non_mrz_lines = [
                                    line for line in lines
                                    if line not in mrz_lines_existing
                                    and not (
                                        (("<" in line.text or "<<" in line.text) and len(line.text) >= 20)
                                        and min(p[1] for p in line.bounding_box) >= min_y * 0.9
                                    )
                                ]
                                lines = non_mrz_lines + tess_ocr_lines
                except Exception as exc:
                    logger.debug("Tesseract MRZ fallback skipped: %s", exc)
                finally:
                    measure("tesseract_mrz_recovery", tess_mrz_started)

            # Next, reread the located MRZ rows themselves with local contrast. This
            # needs no text detection, so it costs a fraction of a page pass.
            mrz_check, mrz_rows = detect_mrz([line for line in lines if line.side == side])
            if (
                config.enable_multivariant_voting
                and mrz_rows
                and mrz_check.checksum_valid is not True
                and not job.cancelled.is_set()
                and hasattr(ocr, "recognize_crop")
            ):
                row_started = time.perf_counter()
                try:
                    from app.schemas.models import OCRObservation
                    from app.services.imaging import text_region_for_ocr
                    reread = []
                    for row in mrz_rows:
                        crop = text_region_for_ocr(corrected, row.bounding_box)
                        if crop is None:
                            reread = []
                            break
                        scale = min(4.0, max(1.0, 48 / crop.shape[0]), 2400 / max(crop.shape[:2]))
                        if scale > 1.0:
                            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                        reading = ocr.recognize_crop(
                            apply_clahe(crop, clip_limit=2.5), language=options.language,
                            cancelled=job.cancelled,
                        )
                        if reading is None:
                            reread = []
                            break
                        text = reading[0].replace(" ", "")
                        prior = row.observations or [OCRObservation(
                            text=row.text, confidence=row.confidence, method="Initial reading")]
                        reread.append(row.model_copy(update={
                            "text": text, "confidence": reading[1], "review_required": True,
                            "recognition_note": "MRZ row reread with local contrast; earlier readings are kept.",
                            "observations": [*prior, OCRObservation(
                                text=text, confidence=reading[1],
                                method="MRZ row crop with local contrast")],
                        }))
                    if reread:
                        row_mrz, _ = detect_mrz(reread)
                        if row_mrz.checksum_valid:
                            originals = {id(row) for row in mrz_rows}
                            lines = [line for line in lines if id(line) not in originals] + reread
                except Exception as exc:
                    logger.debug("MRZ row reread skipped: %s", exc)
                finally:
                    measure("mrz_row_reread", row_started)

            # The slower contrast reread runs only if the checksum is still invalid.
            mrz_check, mrz_rows = detect_mrz([line for line in lines if line.side == side])
            if (
                config.enable_multivariant_voting
                and mrz_check.detected
                and mrz_check.checksum_valid is not True
                and not job.cancelled.is_set()
            ):
                recovery_started = time.perf_counter()
                try:
                    h, w = corrected.shape[:2]
                    mrz_top = int(h * 0.55)
                    mrz_band = corrected[mrz_top:, :]
                    clahe_band = apply_clahe(mrz_band, clip_limit=2.5)
                    variant_lines = ocr.read_plain(
                        clahe_band, side=side, language=options.language, cancelled=job.cancelled,
                    )
                    for v_line in variant_lines:
                        v_line.bounding_box = [[pt[0], pt[1] + mrz_top] for pt in v_line.bounding_box]
                    variant_mrz, variant_rows = detect_mrz(variant_lines)
                    variant_valid_count = sum(1 for v in variant_mrz.checks.values() if v is True)
                    check_valid_count = sum(1 for v in mrz_check.checks.values() if v is True)
                    if variant_mrz.checksum_valid or (
                        variant_mrz.detected
                        and variant_valid_count > check_valid_count
                        and len(variant_mrz.fields) >= len(mrz_check.fields)
                    ):
                        non_mrz_lines = [
                            line for line in lines
                            if not (
                                (("<<" in line.text or "<" in line.text) and len(line.text) >= 20)
                                and min(p[1] for p in line.bounding_box) >= mrz_top * 0.9
                            )
                        ]
                        # The band also contains printed fields. Re-adding them would
                        # duplicate every lower-page line and make its match ambiguous.
                        lines = non_mrz_lines + list(variant_rows)
                except Exception as exc:
                    logger.debug("Multi-variant MRZ recovery skipped: %s", exc)
                finally:
                    measure("mrz_recovery", recovery_started)

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

        # Update image metadata dimensions from corrected images
        for meta in images:
            for side_name, img in corrected_images.items():
                if meta.original_url and f"side={side_name}" in meta.original_url:
                    if hasattr(img, "shape"):
                        meta.width = meta.width or int(img.shape[1])
                        meta.height = meta.height or int(img.shape[0])

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
            images=images,
            ocr_lines=all_lines,
            warnings=list(dict.fromkeys(warnings)),
            timings_ms=timings,
        )
        store.complete(job, result, stored_images)
    except (Cancelled, OCRCancelled):
        return
    except (ImageValidationError, OCRUnavailableError, CapacityError) as exc:
        with store.lock:
            if not job.cancelled.is_set():
                job.status = job.stage = "failed"
                job.error = str(exc)
                job.completed_at = time.monotonic()
    except Exception:
        logger.exception("Unexpected scan failure at stage %s", job.stage)
        with store.lock:
            if not job.cancelled.is_set():
                job.status = job.stage = "failed"
                job.error = "The document could not be processed. Try another image or restart the local scanner."
                job.completed_at = time.monotonic()
    finally:
        uploads.clear()
