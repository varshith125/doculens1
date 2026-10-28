import io

import cv2
import numpy as np
import pytest
from PIL import Image

from app.schemas.models import SideOptions
from app.services.imaging import (
    ImageValidationError,
    assess_quality,
    decode_image,
    detect_corners,
    enhance_for_ocr,
    process_image,
    validate_corners,
)


def document_image() -> np.ndarray:
    image = np.full((700, 1000, 3), 35, dtype=np.uint8)
    cv2.rectangle(image, (130, 140), (870, 580), (240, 240, 240), -1)
    cv2.putText(
        image, "SYNTHETIC DOCUMENT", (170, 235), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (15, 15, 15), 2
    )
    cv2.putText(image, "TEST ONLY", (170, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (15, 15, 15), 2)
    cv2.line(image, (155, 555), (845, 555), (0, 0, 0), 3)
    return image


def test_invalid_bytes_and_non_image_formats_are_rejected():
    for invalid in (b"", b"not an image", b"<svg></svg>"):
        with pytest.raises(ImageValidationError):
            decode_image(invalid)
    output = io.BytesIO()
    Image.new("RGB", (100, 100)).save(output, "BMP")
    with pytest.raises(ImageValidationError, match="JPEG"):
        decode_image(output.getvalue())


def test_decode_honors_exif_and_removes_metadata():
    image = Image.new("RGB", (200, 100), "red")
    exif = Image.Exif()
    exif[274] = 6
    output = io.BytesIO()
    image.save(output, "JPEG", exif=exif)
    decoded = decode_image(output.getvalue())
    assert decoded.shape == (200, 100, 3)
    assert decoded[0, 0, 2] > 240


def test_transparency_is_composited_on_white():
    output = io.BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(output, "PNG")
    assert np.all(decode_image(output.getvalue()) == 255)


def test_dimensions_are_checked_before_full_decode(monkeypatch):
    monkeypatch.setattr("app.services.imaging.MAX_PIXELS", 5000)
    output = io.BytesIO()
    Image.new("RGB", (100, 100)).save(output, "PNG")
    with pytest.raises(ImageValidationError, match="megapixel"):
        decode_image(output.getvalue())


def test_aligned_crop_retains_bottom_content_and_original():
    original = document_image()
    result = process_image(original)
    assert result.metadata.crop_applied
    assert 730 < result.corrected.shape[1] < 780
    assert 430 < result.corrected.shape[0] < 480
    assert result.original is original
    assert (result.corrected[-50:-10].min(axis=2) < 40).any()


@pytest.mark.parametrize("angle", [30, -25, 180])
def test_rotated_document_is_detected_without_losing_edges(angle):
    image = document_image()
    matrix = cv2.getRotationMatrix2D((500, 350), angle, 0.85)
    tilted = cv2.warpAffine(image, matrix, (1000, 700), borderValue=(35, 35, 35))
    result = process_image(tilted)
    assert result.metadata.crop_applied
    assert min(result.corrected.shape[:2]) > 350
    assert max(result.corrected.shape[:2]) > 610


def test_perspective_correction_retains_document():
    document = document_image()[140:581, 130:871]
    source = np.float32([[0, 0], [740, 0], [740, 440], [0, 440]])
    destination = np.float32([[180, 80], [860, 150], [920, 580], [100, 620]])
    transform = cv2.getPerspectiveTransform(source, destination)
    photographed = cv2.warpPerspective(document, transform, (1000, 700), borderValue=(35, 35, 35))
    result = process_image(photographed)
    assert result.metadata.crop_applied
    assert result.corrected.shape[1] > 700
    assert result.corrected.shape[0] > 430
    assert result.metadata.corners[0][1] < 0.15


def test_unknown_boundary_preserves_full_image():
    image = np.full((400, 700, 3), 160, dtype=np.uint8)
    result = process_image(image)
    assert not result.metadata.crop_applied
    assert result.corrected.shape == image.shape
    assert "complete image" in result.metadata.warnings[0]


def test_multiple_documents_require_manual_selection():
    image = np.full((700, 1000, 3), 20, dtype=np.uint8)
    cv2.rectangle(image, (30, 100), (460, 600), (240, 240, 240), -1)
    cv2.rectangle(image, (540, 100), (970, 600), (240, 240, 240), -1)
    result = process_image(image)
    assert not result.metadata.crop_applied
    assert "More than one" in result.metadata.warnings[0]


def test_hough_fallback_does_not_require_contours(monkeypatch):
    monkeypatch.setattr(cv2, "findContours", lambda *args: ([], None))
    corners, _ = detect_corners(document_image())
    assert corners is not None


@pytest.mark.parametrize(
    "corners",
    [
        [[0, 0], [1, 1], [1, 0], [0, 1]],
        [[0, 0], [2, 0], [1, 1], [0, 1]],
        [[0, 0], [1, 0], [1, float("nan")], [0, 1]],
        [[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001]],
    ],
)
def test_invalid_manual_crops_are_rejected(corners):
    with pytest.raises(ImageValidationError):
        validate_corners(corners, 1000, 700)


def test_manual_crop_then_rotation_has_expected_dimensions():
    result = process_image(
        document_image(),
        options=SideOptions(
            corners=[[0.13, 0.2], [0.87, 0.2], [0.87, 0.83], [0.13, 0.83]], rotation=90
        ),
    )
    assert result.metadata.rotation == 90
    assert result.corrected.shape[0] > result.corrected.shape[1]


def test_quality_flags_dark_low_contrast_blur_and_resolution():
    dark = np.full((300, 400, 3), 25, dtype=np.uint8)
    metrics, messages = assess_quality(dark)
    assert metrics["sharpness"] == 0
    assert any("blur" in message for message in messages)
    assert any("Low contrast" in message for message in messages)
    assert any("poorly lit" in message for message in messages)
    assert any("Low resolution" in message for message in messages)


def test_enhancement_is_selective_and_does_not_mutate_original():
    image = document_image()
    assert enhance_for_ocr(image) is image
    dark = np.full((200, 300, 3), 35, dtype=np.uint8)
    before = dark.copy()
    enhanced = enhance_for_ocr(dark)
    assert np.array_equal(dark, before)
    assert enhanced.shape == dark.shape


def test_large_accepted_image_is_bounded_before_ocr(monkeypatch):
    monkeypatch.setattr("app.services.imaging.WORKING_PIXELS", 100_000)
    monkeypatch.setattr("app.services.imaging.WORKING_EDGE", 500)
    output = io.BytesIO()
    Image.new("RGB", (1200, 600), "white").save(output, "JPEG")
    decoded = decode_image(output.getvalue())
    assert decoded.shape[0] * decoded.shape[1] <= 100_000
    assert max(decoded.shape[:2]) <= 500
    assert abs(decoded.shape[1] / decoded.shape[0] - 2) < 0.02


def test_distant_booklet_occupying_ten_percent_of_photo_is_cropped():
    image = np.full((1000, 1500, 3), (90, 110, 140), dtype=np.uint8)
    cv2.rectangle(image, (650, 200), (950, 700), (225, 190, 140), -1)
    cv2.putText(image, "SPECIMEN", (675, 600), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 40), 1)
    processed = process_image(image)
    assert processed.metadata.crop_applied
    assert 295 <= processed.corrected.shape[1] <= 320
    assert 495 <= processed.corrected.shape[0] <= 520


def test_small_image_keeps_context_when_only_an_inner_rectangle_is_detected():
    image = np.full((432, 576, 3), 230, np.uint8)
    cv2.rectangle(image, (180, 120), (500, 300), (80, 80, 80), -1)
    cv2.putText(image, "PASSPORT", (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (10, 10, 10), 2)
    processed = process_image(image)
    assert not processed.metadata.crop_applied
    assert processed.corrected.shape == image.shape
