"""Synthetic text-only cases; no uploaded document or identity values are reused."""

import pytest

from app.extractors.field_extractor import extract_fields
from app.patterns.dates import normalize_date
from app.schemas.models import OCRLine
from app.services.output import prepare_output


def row(text: str, y: int) -> OCRLine:
    return OCRLine(
        text=text, confidence=0.99, side="front",
        bounding_box=[[0, y], [300, y], [300, y + 14], [0, y + 14]],
    )


@pytest.mark.parametrize("text,expected", [
    ("17 MAA/MAR 1987", "1987-03-17"),
    ("18 maart 2021", "2021-03-18"),
    ("07 OKT/OCT 2031", "2031-10-07"),
    ("09 MEI/MAY 2022", "2022-05-09"),
])
def test_dutch_months_preserve_the_printed_four_digit_year(text, expected):
    assert normalize_date(text) == (expected, None)


def test_disagreeing_month_translations_are_not_corrected():
    original = "17 MAA/APR 1987"
    actual, reason = normalize_date(original)
    assert actual == original
    assert reason


def test_native_labels_map_printed_dates_without_mrz():
    result = prepare_output(extract_fields([
        row("Geboortedatum", 0), row("17 MAA/MAR 1987", 19),
        row("Datum van afgifte", 65), row("18 SEP 2021", 84),
        row("Geldig tot", 130), row("17 SEP 2031", 149),
        row("Naam/surname: EXAMPLE", 195),
        row("Voornamen/given names: ALEX MORGAN", 260),
    ]))
    assert not result["mrz"].detected
    fields = result["fields"]
    birth = fields["date_of_birth"]
    assert birth.raw == "17 MAA/MAR 1987"
    assert birth.normalized_value == "1987-03-17"
    assert birth.display_value == "17-March-1987"
    assert fields["date_of_issue"].display_value == "18-September-2021"
    assert fields["date_of_expiry"].display_value == "17-September-2031"
    assert fields["surname"].value == "EXAMPLE"
    assert fields["given_names"].value == "ALEX MORGAN"


@pytest.mark.parametrize("text", ["Sex: V/F", "Geslacht/sex: V", "Sex: Female/F"])
def test_supported_sex_markings_keep_raw_text_and_normalize_display(text):
    field = prepare_output(extract_fields([row(text, 0)]))["fields"]["sex"]
    assert field.value == field.display_value == field.normalized_value == "F"
    assert field.raw == text.split(": ")[1]


@pytest.mark.parametrize("text", ["Sex: M/F", "Sex: V", "Sex: X/F"])
def test_unresolved_sex_markings_are_preserved(text):
    field = extract_fields([row(text, 0)])["fields"]["sex"]
    assert field.status == "uncertain"
    assert field.normalized_value is None
    assert field.observed_value == text.split(": ")[1]


def test_unknown_colon_text_does_not_become_identity_data():
    lines = [row("Promotion: A new product", 0), row("Marker: Annotation", 65),
             row("Occupation: ENGINEER", 130)]
    result = extract_fields(lines)
    assert [field.field_name for field in result["other_fields"]] == ["occupation"]
    assert lines[0].text == "Promotion: A new product"
