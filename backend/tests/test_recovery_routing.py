"""Fictional regressions for missing headings and unresolved passport fields."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.extractors.field_extractor import extract_fields
from app.schemas.models import OCRLine, OCRObservation
from app.services.ocr import OCRService
from app.services.output import prepare_output


def row(text, x=20, y=20, width=150, height=16, confidence=0.99):
    return OCRLine(text=text, confidence=confidence,
                   bounding_box=[[x, y], [x + width, y],
                                 [x + width, y + height], [x, y + height]])


def passport_rows():
    rows = [
        row("REPUBLIC OF INDIA", 155, 20, 300), row("IND", 270, 50, 30),
        row("EXAMPLE", 200, 115), row("ALEX MORGAN", 200, 145),
        row("18/03/1980", 200, 175), row("M", 360, 175, 20),
        row("TESTCITY, TESTSTATE", 200, 205), row("TESTCITY", 200, 235),
        row("18/03/2020", 200, 265), row("18/03/2030", 200, 295),
        row("P<INDEXAMPLE<<ALEX<MORGAN<<<<<<<<<<<<", 20, 350, 540),
    ]
    rows[-1].review_required = True
    rows[-1].observations = [
        OCRObservation(text=rows[-1].text, confidence=0.95, method="Initial reading"),
        OCRObservation(text=rows[-1].text.replace("IND", "IHD"), confidence=0.96,
                       method="Alternate crop"),
    ]
    return rows


def test_corroborated_country_recovers_empty_mrz_slot_and_retains_evidence():
    result = prepare_output(extract_fields(passport_rows(), date_order="dmy"))
    for key, expected in [("country_code", "IND"), ("issuing_country", "India")]:
        field = result["fields"][key]
        assert field.value == expected
        assert field.source == "layout"
        assert field.status == "uncertain"
        assert any(e.source == "visual" and e.raw_text == "IND" for e in field.evidence)
        assert any("IHD" in e.raw_text for e in field.evidence)
    assert "nationality" not in result["fields"]
    assert result["mrz"].checksum_valid is not True


def test_layout_country_does_not_replace_selected_printed_country():
    rows = passport_rows() + [row("Country Code: USA", 20, 390, 300)]
    assert extract_fields(rows)["fields"]["country_code"].value == "USA"


def test_layout_candidate_keeps_missing_heading_explicit_without_selecting_value():
    result = extract_fields(passport_rows(), date_order="dmy")
    fields = {**result["fields"], **{f.field_name: f for f in result["other_fields"]}}
    for key in ("date_of_birth", "date_of_issue", "date_of_expiry", "place_of_birth", "place_of_issue"):
        field = fields[key]
        assert field.value is None
        assert field.validation["heading_unresolved"] is True
        assert any(e.candidate_value for e in field.evidence if e.source == "visual")


@pytest.mark.parametrize("original", ["18/73/2020", "18101/1980", "2/246"])
def test_confident_malformed_numeric_date_gets_two_rereads_without_heading(original):
    line = row(original)
    calls = []

    def engine(image, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(txts=("18/03/2020",), scores=(0.94,))

    OCRService._retry_uncertain_regions(engine, np.full((100, 220, 3), 255, np.uint8), [line])
    assert len(calls) == 2
    assert line.text == "18/03/2020"
    assert line.review_required
    assert line.observations[0].text == original
    assert extract_fields([line])["fields"] == {}  # Rereading does not invent a field heading.


@pytest.mark.parametrize("readings", [
    ["18/03/2020", "18/08/2020"], ["18/03/2020", "18/73/2020"],
    ["NOT A DATE", "NOT A DATE"], ["18/03/20", "18/03/20"],
])
def test_numeric_date_recovery_requires_two_agreeing_complete_dates(readings):
    line = row("18/73/2020", confidence=0.90)
    responses = iter(readings)

    def engine(image, **kwargs):
        return SimpleNamespace(txts=(next(responses),), scores=(0.99,))

    OCRService._retry_uncertain_regions(engine, np.full((100, 220, 3), 255, np.uint8), [line])
    assert line.text == "18/73/2020"
    assert line.review_required


@pytest.mark.parametrize("text", ["18/03/2020", "03/04/2020", "12345678"])
def test_confident_valid_or_ambiguous_date_does_not_trigger_malformed_date_retry(text):
    def engine(*args, **kwargs):
        pytest.fail("A valid or order-ambiguous date is not malformed")

    OCRService._retry_uncertain_regions(engine, np.full((100, 220, 3), 255, np.uint8), [row(text)])


def test_invalid_dates_receive_bounded_retries_before_low_confidence_noise():
    dates = [row(text, y=i * 25) for i, text in enumerate(["18/73/2020", "18101/1980", "2/246"])]
    noise = [row("NOISE", y=(i + 3) * 25, confidence=0.4) for i in range(8)]
    calls = []

    def engine(image, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(txts=("UNCLEAR",), scores=(0.5,))

    OCRService._retry_uncertain_regions(engine, np.full((400, 220, 3), 255, np.uint8), noise + dates)
    assert all(len(line.observations) == 3 for line in dates)
    assert len(calls) <= 12
    assert not noise[-1].observations


def test_tiny_caption_enlargement_restores_boxes_and_keeps_value_readings():
    caption = row("garbled caption", y=20, height=8)
    value = row("18/03/1980", y=38, height=8)
    lines = [caption, value, row("OTHER", y=65, height=8),
             row("P<UTOEXAMPLE<<ALEX<<<<<<<<<<<<<<<<<<<<", x=10, y=180, width=310)]
    calls = []

    def engine(image, **kwargs):
        calls.append(image.shape)
        return SimpleNamespace(
            boxes=[(np.asarray(line.bounding_box) * 4).tolist() for line in [caption, value]],
            txts=("Date of birth", "DIFFERENT VALUE"), scores=(0.97, 0.99),
        )

    OCRService._recover_small_captions(engine, np.full((220, 340, 3), 255, np.uint8), lines, "front")
    assert calls == [(720, 1360, 3)]
    assert caption.text == "Date of birth"
    assert caption.bounding_box == [[20, 20], [170, 20], [170, 28], [20, 28]]
    assert caption.observations[0].text == "garbled caption"
    assert caption.review_required
    assert value.text == "18/03/1980"
    assert extract_fields(lines, date_order="dmy")["fields"]["date_of_birth"].value == "1980-03-18"
