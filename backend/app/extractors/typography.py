"""Relative typography cues; no font-size cutoff or document template."""

import math
import unicodedata

import cv2
import numpy as np

from app.schemas.models import OCRLine, TextAppearance


def text_dimensions(line: OCRLine) -> tuple[float, float]:
    points = line.bounding_box
    width = (math.dist(points[0], points[1]) + math.dist(points[2], points[3])) / 2
    height = (math.dist(points[1], points[2]) + math.dist(points[3], points[0])) / 2
    return max(line.text_width or width, 1e-6), max(line.text_height or height, 1e-6)


def _script(line: OCRLine) -> str:
    scripts = [unicodedata.name(c, "").split(" ")[0] for c in line.text if c.isalpha()]
    return max(set(scripts), key=scripts.count) if scripts else ""


def prominence(label: OCRLine, value: OCRLine) -> float:
    """A bounded scoring bonus, never permission to cross a field boundary.

    Character advance supplements box height only for the same script. Whole
    text width is not font size: a three-language heading is often very wide.
    """
    lw, lh = text_dimensions(label)
    vw, vh = text_dimensions(value)
    ratio = vh / lh
    if label.appearance and value.appearance:
        ratio = math.sqrt(ratio * value.appearance.ink_height / label.appearance.ink_height)
    signal = max(-1.0, min(1.0, math.log2(max(ratio, 1e-6))))
    if _script(label) == _script(value):
        counts = [max(1, sum(c.isalnum() for c in row.text)) for row in (label, value)]
        advance = (vw / counts[1]) / (lw / counts[0])
        signal = 0.85 * signal + 0.15 * max(-1.0, min(1.0, math.log2(max(advance, 1e-6))))
        if label.appearance and value.appearance:
            weight = value.appearance.stroke_ratio / label.appearance.stroke_ratio
            signal += 0.1 * max(-1.0, min(1.0, math.log2(max(weight, 1e-6))))
    return max(-0.8, min(0.8, signal * 0.8))


def measure_appearance(image: np.ndarray, lines: list[OCRLine]) -> None:
    """Measure plausible ink components inside rectified OCR polygons.

    Crop size is capped for cost only. Component filters are ratios of the crop;
    noisy, blank, clipped, or decorative crops fall back to OCR geometry.
    This estimates ink height/weight, not font family or typographic point size.
    """
    for line in lines:
        line.appearance = None
        width, height = text_dimensions(line)
        points = np.asarray(line.bounding_box, dtype=np.float32)
        if (points.shape != (4, 2) or not np.isfinite(points).all()
                or width < 2 or height < 2
                or (points[:, 0] < 0).any() or (points[:, 1] < 0).any()
                or (points[:, 0] >= image.shape[1]).any()
                or (points[:, 1] >= image.shape[0]).any()):
            continue
        scale = min(1.0, 512 / width, 96 / height)
        w, h = max(2, round(width * scale)), max(2, round(height * scale))
        target = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        crop = cv2.warpPerspective(image, cv2.getPerspectiveTransform(points, target), (w, h))
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        if float(np.std(gray)) < 1:
            continue
        _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        if np.count_nonzero(ink) > ink.size / 2:
            ink = 255 - ink
        count, components, stats, _ = cv2.connectedComponentsWithStats(ink)
        valid = [i for i in range(1, count)
                 if 0.2 * h <= stats[i, cv2.CC_STAT_HEIGHT] <= 0.98 * h
                 and stats[i, cv2.CC_STAT_WIDTH] <= 0.9 * w
                 and 0.001 * ink.size <= stats[i, cv2.CC_STAT_AREA] <= 0.5 * ink.size]
        if not valid:
            continue
        mask = np.isin(components, valid).astype(np.uint8)
        coverage = np.count_nonzero(mask) / mask.size
        if not 0.015 <= coverage <= 0.55:
            continue
        ink_height = float(np.median(stats[valid, cv2.CC_STAT_HEIGHT]))
        distances = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
        stroke = float(np.median(distances[mask != 0])) * 2 / ink_height
        line.appearance = TextAppearance(ink_height=ink_height / scale, stroke_ratio=min(1, stroke))
