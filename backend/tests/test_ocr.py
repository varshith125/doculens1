from types import SimpleNamespace

import numpy as np
import pytest

from app.schemas.models import OCRLine
from app.services.ocr import OCRService, OCRUnavailableError, _rotate_lines, normalize_output


def test_output_normalization_keeps_text_scores_boxes_and_side():
    output = SimpleNamespace(
        boxes=np.array(
            [[[10, 30], [100, 30], [100, 45], [10, 45]], [[10, 5], [100, 5], [100, 20], [10, 20]]]
        ),
        txts=("SECOND LINE", "  FIRST LINE  "),
        scores=(0.5, 0.99),
    )
    lines = normalize_output(output, "back", (5, 10))
    assert [line.text for line in lines] == ["FIRST LINE", "SECOND LINE"]
    assert lines[0].confidence == 0.99
    assert lines[0].bounding_box[0] == [15, 15]
    assert lines[0].side == "back"


def test_empty_and_malformed_ocr_observations_are_not_invented():
    assert normalize_output(SimpleNamespace(boxes=None, txts=None, scores=None)) == []
    output = SimpleNamespace(
        boxes=[[[0, 0]] * 4] * 2, txts=("", "value"), scores=(0.7, float("nan"))
    )
    assert normalize_output(output) == []


def test_rotated_boxes_remain_in_corrected_coordinates():
    line = OCRLine(
        text="TEST", confidence=0.9, bounding_box=[[20, 10], [70, 10], [70, 30], [20, 30]]
    )
    rotated = _rotate_lines([line], 100, 50, 90)[0]
    assert rotated.bounding_box == [[39, 20], [39, 70], [19, 70], [19, 20]]
    assert rotated.text == line.text


def test_missing_arabic_model_is_not_advertised(monkeypatch):
    monkeypatch.delenv("DOCULENS_ARABIC_MODEL_PATH", raising=False)
    service = OCRService(arabic_model_path="/missing/arabic.onnx")
    assert service.languages == ["latin"]
    with pytest.raises(OCRUnavailableError, match="not installed"):
        service.read(np.ones((100, 200, 3), dtype=np.uint8), language="arabic")


def test_region_retry_preserves_uncorroborated_text():
    line = OCRLine(
        text="UNCLEAR", confidence=0.5, bounding_box=[[0, 0], [100, 0], [100, 25], [0, 25]]
    )
    calls = []

    def engine(image, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            txts=("DIFFERENT" if len(calls) == 1 else "ANOTHER",), scores=np.array([0.99])
        )

    OCRService._retry_uncertain_regions(engine, np.full((60, 150, 3), 255, np.uint8), [line])
    assert line.text == "UNCLEAR"
    assert line.confidence == 0.5
    assert calls[0]["use_det"] is False
    assert line.review_required
    assert len(line.observations) == 3


def test_agreeing_enhanced_reads_are_used_with_original_evidence():
    line = OCRLine(
        text="TEST PERS0N", confidence=0.6, bounding_box=[[0, 0], [100, 0], [100, 25], [0, 25]]
    )

    def engine(image, **kwargs):
        return SimpleNamespace(txts=("TEST PERSON",), scores=np.array([0.96]))

    OCRService._retry_uncertain_regions(engine, np.full((60, 150, 3), 255, np.uint8), [line])
    assert line.text == "TEST PERSON"
    assert line.review_required
    assert line.observations[0].text == "TEST PERS0N"
    assert line.confidence == 0.96


def test_weak_agreement_does_not_replace_initial_reading():
    line = OCRLine(
        text="FIRST", confidence=0.8, bounding_box=[[0, 0], [100, 0], [100, 25], [0, 25]]
    )

    def engine(image, **kwargs):
        return SimpleNamespace(txts=("SECOND",), scores=(0.84,))

    OCRService._retry_uncertain_regions(engine, np.full((60, 150, 3), 255, np.uint8), [line])
    assert line.text == "FIRST"
    assert line.review_required


def test_invalid_month_gets_observed_date_candidate_without_character_substitution():
    line = OCRLine(
        text="21 0CT 2025", confidence=0.99, bounding_box=[[0, 0], [140, 0], [140, 25], [0, 25]]
    )
    responses = iter(["21 OCT 2025", "21 0CT 2025"])

    def engine(image, **kwargs):
        return SimpleNamespace(txts=(next(responses),), scores=(0.96,))

    OCRService._retry_uncertain_regions(engine, np.full((60, 180, 3), 255, np.uint8), [line])
    assert line.text == "21 OCT 2025"
    assert line.review_required
    assert line.observations[0].text == "21 0CT 2025"


def test_invalid_month_is_not_rewritten_if_no_reread_observes_valid_month():
    line = OCRLine(
        text="21 0CT 2025", confidence=0.99, bounding_box=[[0, 0], [140, 0], [140, 25], [0, 25]]
    )

    def engine(image, **kwargs):
        return SimpleNamespace(txts=("21 0CT 2025",), scores=(0.99,))

    OCRService._retry_uncertain_regions(engine, np.full((60, 180, 3), 255, np.uint8), [line])
    assert line.text == "21 0CT 2025"


def test_orientation_requires_multiple_agreeing_confident_lines():
    line = OCRLine(
        text="EXAMPLE", confidence=0.95, bounding_box=[[5, 5], [150, 5], [150, 30], [5, 30]]
    )
    image = np.full((100, 200, 3), 255, np.uint8)

    def engine(*args, **kwargs):
        return SimpleNamespace(cls_res=[("180", 0.99)])

    assert OCRService._orientation(engine, image, [line]) == 0
    assert OCRService._orientation(engine, image, [line, line]) == 180
