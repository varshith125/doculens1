"""Second readings of a machine-readable zone whose check digits do not pass.

Three strategies run from cheapest to most expensive, and each stops the chain
once the MRZ validates:

1. Tesseract rereads the MRZ block (when installed).
2. The located MRZ rows are reread one by one with local contrast.
3. The lower page band is detected and read again with local contrast.

A reading only replaces the original when it validates, or passes more checks
than the reading it replaces.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from app.core.config import Settings
from app.extractors import mrz_parser
from app.extractors.mrz_anchor import aligned_numeric_row
from app.schemas.models import MRZResult, OCRLine, OCRObservation, Side
from app.services.imaging import apply_clahe, text_region_for_ocr

logger = logging.getLogger(__name__)

Measure = Callable[[str, float], None]

# MRZ rows are 30, 36 or 44 characters; shorter strings with fillers are not rows.
MIN_MRZ_LENGTH = 20
# The MRZ sits in the lower part of every ICAO travel document page.
MRZ_BAND_TOP = 0.55
BLOCK_PADDING = 6


def _looks_like_mrz(line: OCRLine) -> bool:
    return "<" in line.text and len(line.text.replace(" ", "")) >= MIN_MRZ_LENGTH


def _passed_checks(mrz: MRZResult) -> int:
    return sum(1 for passed in mrz.checks.values() if passed is True)


def _improves(candidate: MRZResult, current: MRZResult) -> bool:
    return bool(candidate.checksum_valid
                or (candidate.detected and _passed_checks(candidate) > _passed_checks(current)))


def _detect(lines: list[OCRLine], side: Side) -> tuple[MRZResult, list[OCRLine]]:
    mrz, rows = mrz_parser.detect_mrz([line for line in lines if line.side == side])
    return mrz, list(rows)


def _replace_mrz_below(lines: list[OCRLine], top: float, replacement: list[OCRLine]) -> list[OCRLine]:
    """Swap every MRZ-like line at or below ``top`` for ``replacement``."""
    kept = [line for line in lines
            if not (_looks_like_mrz(line) and min(p[1] for p in line.bounding_box) >= top)]
    return kept + replacement


def _tesseract_block(lines: list[OCRLine], image: np.ndarray, side: Side,
                     tesseract: Any, current: MRZResult) -> list[OCRLine] | None:
    rows = [line for line in lines if line.side == side and _looks_like_mrz(line)]
    if not rows:
        return None
    height, width = image.shape[:2]
    points = np.asarray([p for row in rows for p in row.bounding_box])
    left, top = np.maximum(points.min(axis=0).astype(int) - BLOCK_PADDING, 0)
    right = min(width, int(points[:, 0].max()) + BLOCK_PADDING)
    bottom = min(height, int(points[:, 1].max()) + BLOCK_PADDING)
    readings = tesseract.recognize_mrz_block(image[top:bottom, left:right], psm=6)
    if not readings:
        return None
    row_height = (bottom - top) / len(readings)
    recovered = []
    for index, (text, confidence) in enumerate(readings):
        row_top, row_bottom = top + index * row_height, top + (index + 1) * row_height
        recovered.append(OCRLine(
            text=text, confidence=confidence, side=side, review_required=True,
            bounding_box=[[float(left), row_top], [float(right), row_top],
                          [float(right), row_bottom], [float(left), row_bottom]],
            observations=[OCRObservation(text=text, confidence=confidence,
                                         method="Tesseract fallback: MRZ block")],
            recognition_note="MRZ recovered by Tesseract backup engine.",
        ))
    candidate, _ = mrz_parser.detect_mrz(recovered)
    if not _improves(candidate, current):
        return None
    return _replace_mrz_below([line for line in lines if line not in rows], top * 0.9, recovered)


def _reread_rows(lines: list[OCRLine], image: np.ndarray, rows: list[OCRLine],
                 ocr: Any, language: str, cancelled: threading.Event) -> list[OCRLine] | None:
    reread = []
    for row in rows:
        crop = text_region_for_ocr(image, row.bounding_box)
        if crop is None:
            return None
        scale = min(4.0, max(1.0, 48 / crop.shape[0]), 2400 / max(crop.shape[:2]))
        if scale > 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        reading = ocr.recognize_crop(apply_clahe(crop, clip_limit=2.5), language=language,
                                     cancelled=cancelled)
        if reading is None:
            return None
        text, confidence = reading[0].replace(" ", ""), reading[1]
        prior = row.observations or [OCRObservation(
            text=row.text, confidence=row.confidence, method="Initial reading")]
        reread.append(row.model_copy(update={
            "text": text, "confidence": confidence, "review_required": True,
            "recognition_note": "MRZ row reread with local contrast; earlier readings are kept.",
            "observations": [*prior, OCRObservation(text=text, confidence=confidence,
                                                    method="MRZ row crop with local contrast")],
        }))
    candidate, _ = mrz_parser.detect_mrz(reread)
    if not candidate.checksum_valid:
        return None
    originals = {id(row) for row in rows}
    return [line for line in lines if id(line) not in originals] + reread


def _reread_band(lines: list[OCRLine], image: np.ndarray, side: Side, ocr: Any,
                 language: str, cancelled: threading.Event, current: MRZResult) -> list[OCRLine] | None:
    top = int(image.shape[0] * MRZ_BAND_TOP)
    band = apply_clahe(image[top:, :], clip_limit=2.5)
    reading = ocr.read_plain(band, side=side, language=language, cancelled=cancelled)
    for line in reading:
        line.bounding_box = [[x, y + top] for x, y in line.bounding_box]
    candidate, rows = mrz_parser.detect_mrz(reading)
    if not (_improves(candidate, current) and len(candidate.fields) >= len(current.fields)):
        return None
    # The band also holds printed fields; only its MRZ rows are adopted, so no
    # printed line is duplicated.
    return _replace_mrz_below(lines, top * 0.9, list(rows))


def recover_mrz(lines: list[OCRLine], image: np.ndarray, side: Side, *, ocr: Any,
                config: Settings, language: str, cancelled: threading.Event,
                measure: Measure) -> list[OCRLine]:
    """Return ``lines`` with the MRZ rows replaced by a better reading, if one is found."""
    def attempt(name: str, strategy: Callable[[], list[OCRLine] | None]) -> None:
        nonlocal lines
        started = time.perf_counter()
        try:
            lines = strategy() or lines
        except Exception as exc:  # A second reading is optional; keep the first.
            logger.debug("MRZ recovery step %s skipped: %s", name, exc)
        finally:
            measure(name, started)

    current, _ = _detect(lines, side)
    tesseract = getattr(ocr, "tesseract", None)
    if (config.enable_tesseract_backup and current.detected and current.checksum_valid is not True
            and not cancelled.is_set() and tesseract is not None and tesseract.is_available()):
        attempt("tesseract_mrz_recovery",
                lambda: _tesseract_block(lines, image, side, tesseract, current))

    current, rows = _detect(lines, side)
    if (config.enable_multivariant_voting and rows and current.checksum_valid is not True
            and not cancelled.is_set() and hasattr(ocr, "recognize_crop")):
        attempt("mrz_row_reread",
                lambda: _reread_rows(lines, image, rows, ocr, language, cancelled))

    current, rows = _detect(lines, side)
    numeric_row_checked = len(rows) == 2 and aligned_numeric_row(rows[1].text) is not None
    if (config.enable_multivariant_voting and current.detected and current.checksum_valid is not True
            and not numeric_row_checked and not cancelled.is_set()):
        # A checked second row leaves only the name row, which has no check digit
        # and is confirmed against the printed names instead.
        attempt("mrz_recovery",
                lambda: _reread_band(lines, image, side, ocr, language, cancelled, current))
    return lines
