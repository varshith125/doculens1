from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.schemas.models import ImageResult, Side, SideOptions

MAX_PIXELS = 40_000_000
WORKING_PIXELS = 16_000_000
WORKING_EDGE = 6000
MAX_EDGE = 12_000
MAX_IMAGE_BYTES = 12 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageValidationError(ValueError):
    pass


@dataclass
class ProcessedImage:
    original: np.ndarray
    corrected: np.ndarray
    metadata: ImageResult


def decode_image(data: bytes) -> np.ndarray:
    """Verify dimensions before allocation and normalize EXIF orientation once."""
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageValidationError("Image must be between 1 byte and 12 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as header:
                width, height = header.size
                if header.format not in SUPPORTED_FORMATS:
                    raise ImageValidationError("Upload a JPEG, PNG, or WebP image.")
                if getattr(header, "n_frames", 1) != 1:
                    raise ImageValidationError("Animated or multi-frame images are not supported.")
                if width * height > MAX_PIXELS or max(width, height) > MAX_EDGE:
                    raise ImageValidationError(
                        "Image exceeds the 40 megapixel or 12000 pixel limit."
                    )
                if min(width, height) < 64:
                    raise ImageValidationError(
                        "Image is too small; both dimensions must be at least 64 pixels."
                    )
                header.verify()
            with Image.open(io.BytesIO(data)) as source:
                normalized = ImageOps.exif_transpose(source)
                width, height = normalized.size
                scale = min(
                    1, WORKING_EDGE / max(width, height), (WORKING_PIXELS / (width * height)) ** 0.5
                )
                if scale < 1:
                    normalized.thumbnail(
                        (int(width * scale), int(height * scale)), Image.Resampling.LANCZOS
                    )
                if normalized.mode in {"RGBA", "LA"} or "transparency" in normalized.info:
                    rgba = normalized.convert("RGBA")
                    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    normalized = Image.alpha_composite(white, rgba)
                rgb = np.asarray(normalized.convert("RGB"))
                return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except ImageValidationError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ImageValidationError("The image is damaged or could not be decoded.") from exc


def encode_jpeg(image: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not success:
        raise ImageValidationError("The corrected image could not be encoded.")
    return encoded.tobytes()


def rotate_image(image: np.ndarray, degrees: int) -> np.ndarray:
    rotations = {
        90: cv2.ROTATE_90_CLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE,
    }
    return cv2.rotate(image, rotations[degrees]) if degrees in rotations else image


def _order_corners(points: np.ndarray) -> np.ndarray:
    center = points.mean(axis=0)
    ordered = points[np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))]
    return np.roll(ordered, -int(np.argmin(ordered.sum(axis=1))), axis=0).astype(np.float32)


def validate_corners(corners: list[list[float]], width: int, height: int) -> np.ndarray:
    try:
        points = np.asarray(corners, dtype=np.float32)
    except (ValueError, TypeError) as exc:
        raise ImageValidationError("Crop corners must contain four coordinate pairs.") from exc
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ImageValidationError("Crop corners must contain four finite coordinate pairs.")
    if np.any(points < 0) or np.any(points > 1):
        raise ImageValidationError("Crop corners must be inside the image.")
    pixels = points * np.array([width - 1, height - 1], dtype=np.float32)
    if not cv2.isContourConvex(pixels) or cv2.contourArea(pixels) < width * height * 0.02:
        raise ImageValidationError(
            "Crop corners must form a non-crossing quadrilateral covering at least 2% of the image."
        )
    if min(np.linalg.norm(pixels[(i + 1) % 4] - pixels[i]) for i in range(4)) < 32:
        raise ImageValidationError("The selected document region is too small.")
    return _order_corners(pixels)


def _warp(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    top_left, top_right, bottom_right, bottom_left = corners
    width = int(
        round(max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left)))
    )
    height = int(
        round(max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right)))
    )
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    transform = cv2.getPerspectiveTransform(corners, target)
    return cv2.warpPerspective(
        image, transform, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def _candidate_score(points: np.ndarray, size: tuple[int, int]) -> float:
    height, width = size
    area_ratio = cv2.contourArea(points) / (width * height)
    if not 0.045 <= area_ratio <= 0.97:
        return 0
    lengths = np.array([np.linalg.norm(points[(i + 1) % 4] - points[i]) for i in range(4)])
    if lengths.min() < min(width, height) * 0.08:
        return 0
    ratio = (lengths[0] + lengths[2]) / (lengths[1] + lengths[3])
    if not 0.38 < ratio < 2.65:
        return 0
    cosines = []
    for index in range(4):
        first = points[(index - 1) % 4] - points[index]
        second = points[(index + 1) % 4] - points[index]
        cosines.append(
            abs(float(np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second))))
        )
    if max(cosines) > 0.7:
        return 0
    return float(area_ratio * (1 - 0.35 * np.mean(cosines)))


def _line_candidate(edges: np.ndarray) -> np.ndarray | None:
    """A Hough-line fallback can bridge broken edges without assuming a contour."""
    minimum = int(min(edges.shape) * 0.28)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 80, minLineLength=minimum, maxLineGap=20)
    if lines is None or len(lines) < 4:
        return None
    endpoints = lines[:, 0].reshape(-1, 2).astype(np.float32)
    rectangle = _order_corners(cv2.boxPoints(cv2.minAreaRect(endpoints)))
    if not _candidate_score(rectangle, edges.shape):
        return None
    perimeter = np.zeros_like(edges)
    cv2.polylines(perimeter, [rectangle.astype(np.int32)], True, 255, 4)
    dilated = cv2.dilate(edges, np.ones((5, 5), np.uint8))
    coverage = np.count_nonzero(cv2.bitwise_and(perimeter, dilated)) / max(
        1, np.count_nonzero(perimeter)
    )
    return rectangle if coverage > 0.75 else None


def detect_corners(image: np.ndarray) -> tuple[np.ndarray | None, list[str]]:
    height, width = image.shape[:2]
    scale = min(1.0, 1400 / max(height, width))
    small = (
        cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1
        else image
    )
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 45, 130)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    _, threshold = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates: list[tuple[float, np.ndarray]] = []
    for mask in (closed, threshold, cv2.bitwise_not(threshold)):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
            polygon = cv2.approxPolyDP(contour, 0.018 * cv2.arcLength(contour, True), True)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            points = _order_corners(polygon[:, 0])
            score = _candidate_score(points, gray.shape)
            if score and not any(
                np.mean(np.linalg.norm(points - old, axis=1)) < 12 for _, old in candidates
            ):
                candidates.append((score, points))
    if not candidates:
        # Colored booklet paper can have broken grayscale edges against desks/fabric.
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        paper = cv2.inRange(hsv, np.array([80, 25, 60]), np.array([130, 255, 255]))
        paper = cv2.morphologyEx(paper, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(paper, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
            polygon = cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True)
            if len(polygon) == 4 and cv2.isContourConvex(polygon):
                points = _order_corners(polygon[:, 0])
                score = _candidate_score(points, gray.shape)
                if score:
                    candidates.append((score, points))
    if not candidates:
        line_points = _line_candidate(edges)
        if line_points is not None:
            candidates.append((_candidate_score(line_points, gray.shape), line_points))
    if not candidates:
        return None, [
            "Document boundary is uncertain. The complete image was retained; adjust the four corners if needed."
        ]
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    best = candidates[0][1]
    if max(height, width) < 1000 and cv2.contourArea(best) / (gray.shape[0] * gray.shape[1]) < 0.5:
        return None, [
            "The proposed crop could remove document context from this small image. The complete image was retained; adjust the corners if needed."
        ]
    for _, other in candidates[1:]:
        overlap, _ = cv2.intersectConvexConvex(best, other)
        if overlap / min(cv2.contourArea(best), cv2.contourArea(other)) < 0.25:
            return None, [
                "More than one possible document was found. Upload one document per side or select its four corners."
            ]
    center = best.mean(axis=0)
    padded = (center + (best - center) * 1.016) / scale
    padded[:, 0] = np.clip(padded[:, 0], 0, width - 1)
    padded[:, 1] = np.clip(padded[:, 1], 0, height - 1)
    return padded.astype(np.float32), [
        "Automatic crop is an estimate. Compare it with the original and check every edge."
    ]


def assess_quality(image: np.ndarray) -> tuple[dict[str, float], list[str]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sample = cv2.resize(
        gray,
        None,
        fx=min(1, 1200 / max(gray.shape)),
        fy=min(1, 1200 / max(gray.shape)),
        interpolation=cv2.INTER_AREA,
    )
    metrics = {
        "sharpness": round(float(cv2.Laplacian(sample, cv2.CV_64F).var()), 2),
        "brightness": round(float(sample.mean()), 2),
        "contrast": round(float(sample.std()), 2),
        "overexposed_fraction": round(float(np.mean(sample >= 250)), 4),
        "dark_fraction": round(float(np.mean(sample <= 30)), 4),
    }
    quadrant_means = [
        part.mean() for row in np.array_split(sample, 2) for part in np.array_split(row, 2, axis=1)
    ]
    metrics["lighting_spread"] = round(float(np.ptp(quadrant_means)), 2)
    median = cv2.medianBlur(sample, 3)
    metrics["noise_estimate"] = round(float(np.median(np.abs(sample.astype(float) - median))), 2)
    messages = []
    if metrics["sharpness"] < 55:
        messages.append("The image may be blurred. Retake it in focus if characters are missing.")
    if metrics["contrast"] < 28:
        messages.append("Low contrast may hide faint printed details.")
    if metrics["brightness"] < 65 or metrics["dark_fraction"] > 0.45:
        messages.append("The document is poorly lit. Use even, indirect light.")
    if metrics["overexposed_fraction"] > 0.65:
        messages.append("Bright or washed-out regions may conceal text; check for glare.")
    if metrics["lighting_spread"] > 65:
        messages.append("Uneven lighting or shadows may reduce recognition accuracy.")
    if metrics["noise_estimate"] > 8:
        messages.append("Image noise may reduce recognition accuracy.")
    if min(image.shape[:2]) < 500:
        messages.append("Low resolution: use a larger image for small text and the MRZ.")
    return metrics, messages


def enhance_for_ocr(image: np.ndarray) -> np.ndarray:
    """Apply contrast correction only when measured darkness or contrast warrants it."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.std() >= 32 and gray.mean() >= 70:
        return image
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=1.7, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def process_image(
    image: np.ndarray, side: Side = "front", options: SideOptions | None = None
) -> ProcessedImage:
    options = options or SideOptions()
    height, width = image.shape[:2]
    if options.corners is not None:
        corners = validate_corners(options.corners, width, height)
        messages = ["A manual crop was applied. Check that all printed content remains visible."]
    else:
        corners, messages = detect_corners(image)
    crop_applied = corners is not None
    corrected = _warp(image, corners) if corners is not None else image
    corrected = rotate_image(corrected, options.rotation)
    if corners is None:
        corners = np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
        )
    quality, quality_messages = assess_quality(corrected)
    normalized = corners / np.array([width - 1, height - 1])
    metadata = ImageResult(
        side=side,
        width=corrected.shape[1],
        height=corrected.shape[0],
        corners=np.round(normalized, 6).tolist(),
        crop_applied=crop_applied,
        rotation=options.rotation,
        quality=quality,
        warnings=messages + quality_messages,
    )
    return ProcessedImage(original=image, corrected=corrected, metadata=metadata)
