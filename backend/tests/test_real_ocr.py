import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.store import ScanStore
from app.extractors.field_extractor import extract_fields
from app.schemas.models import ScanOptions, SideOptions
from app.services.imaging import decode_image
from app.services.ocr import OCRService
from app.services.pipeline import run_scan

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DOCULENS_TEST_REAL_OCR") != "1",
        reason="Set DOCULENS_TEST_REAL_OCR=1 to exercise installed ONNX models.",
    ),
]


@pytest.fixture(scope="module")
def engine():
    service = OCRService()
    service.warmup()
    return service


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_real_latin_recognition_and_orientation(engine, rotation):
    image = np.full((420, 900, 3), 255, np.uint8)
    for y, text in [
        (80, "DOCULENS SPECIMEN"),
        (170, "SURNAME: EXAMPLE"),
        (260, "NATIONALITY: UTOPIA"),
    ]:
        cv2.putText(image, text, (35, y), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2, cv2.LINE_AA)
    if rotation:
        code = {
            90: cv2.ROTATE_90_CLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE,
        }[rotation]
        image = cv2.rotate(image, code)
    _, lines, corrected = engine.read_oriented(image)
    assert any("DOCULENS" in line.text for line in lines)
    assert any("EXAMPLE" in line.text for line in lines)
    assert (rotation + corrected) % 360 == 0
    assert all(len(line.bounding_box) == 4 for line in lines)


def test_real_arabic_keeps_logical_text(engine):
    fixture = Path(__file__).resolve().parents[2] / "docs" / "arabic-specimen.png"
    if "arabic" not in engine.languages:
        pytest.skip("Optional Arabic recognizer not installed")
    lines = engine.read(decode_image(fixture.read_bytes()), language="arabic")
    assert any("الجنسية" in line.text for line in lines)
    assert any("SYNTHETIC TEST ONLY" in line.text for line in lines)
    assert not any("ةيسنجلا" in line.text for line in lines)


def test_real_wrapped_name_keeps_both_lines(engine):
    image = np.full((360, 1000, 3), 255, np.uint8)
    for y, text in [
        (55, "FICTIONAL ID - TEST ONLY"),
        (140, "Name: ALEX MORGAN EXAMPLE"),
        (172, "TESTPERSON"),
        (240, "Nationality: India"),
    ]:
        cv2.putText(image, text, (45, y), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 0, 0), 1, cv2.LINE_AA)
    fields = extract_fields(engine.read(image))["fields"]
    assert fields["full_name"].value == "ALEX MORGAN EXAMPLE TESTPERSON"
    assert fields["full_name"].status == "detected"
    assert fields["nationality"].value == "India"


@pytest.mark.parametrize("angle,scale", [(15, 0.45), (11, 0.4), (18, 0.5)])
def test_small_blurred_tilted_document_maps_actual_ocr_values(engine, angle, scale):
    # Ground truth comes from the fictional rendering source, never model output.
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_accuracy.py"
    spec = importlib.util.spec_from_file_location("accuracy_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    image = module.cases()[f"distant_blur_tilt_{angle}"]
    fields = extract_fields(engine.read(image), date_order="dmy")["fields"]
    assert all(
        fields.get(name) and fields[name].value == value for name, value in module.EXPECTED.items()
    )


def test_uniform_unrecoverable_pixels_do_not_create_identity_values(engine):
    lines = engine.read(np.full((320, 500, 3), 220, np.uint8))
    assert lines == []
    assert extract_fields(lines)["fields"] == {}


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_manual_rotation_preserves_passport_fields_and_mrz(engine, rotation):
    """Exercise the same rotation option sent by the app's Rotate button."""
    fixture = Path(__file__).resolve().parents[2] / "docs" / "specimen.png"
    store = ScanStore(retention=600, capacity=1, max_bytes=32 * 1024 * 1024)
    job = store.create("fictional-passport-rotation")
    try:
        run_scan(
            job, {"front": fixture.read_bytes()},
            ScanOptions(front=SideOptions(rotation=rotation)), store, engine,
        )
        assert job.status == "completed", job.error
        result = job.result
        assert result is not None
        expected = {
            "surname": "ERIKSSON", "given_names": "ANNA MARIA",
            "document_number": "L898902C3", "nationality": "UTO",
            "date_of_birth": "1974-08-12", "date_of_expiry": "2012-04-15", "sex": "F",
        }
        assert {key: result.fields[key].value for key in expected} == expected
        assert result.mrz.checksum_valid is True
        assert result.images[0].rotation == 0
        assert result.images[0].width > result.images[0].height
    finally:
        store.clear()
