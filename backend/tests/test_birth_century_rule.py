import pytest

from app.extractors.field_extractor import extract_fields
from app.extractors.mrz_parser import check_digit
from app.patterns.dates import normalize_mrz_date_century
from app.schemas.models import OCRLine
from app.services.output import prepare_output


def row(text, y):
    return OCRLine(text=text, confidence=0.99,
                   bounding_box=[[0, y], [800, y], [800, y + 20], [0, y + 20]])


def document(birth, expiry="300415"):
    first = "P<UTOEXAMPLE<<TEST".ljust(44, "<")
    number = "L898902C3"
    second = (number + check_digit(number) + "UTO" + birth + check_digit(birth)
              + "F" + expiry + check_digit(expiry) + "<" * 14 + "0")
    second += check_digit(second[:10] + second[13:20] + second[21:43])
    return [row(first, 500), row(second, 530)]


@pytest.mark.parametrize("raw,expected", [
    ("000229", "2000-02-29"), ("041123", "2004-11-23"),
    ("260101", "2026-01-01"), ("270101", "1927-01-01"),
    ("620801", "1962-08-01"), ("991231", "1999-12-31"),
])
def test_birth_rule_reaches_final_output_and_preserves_raw_mrz(raw, expected):
    result = prepare_output(extract_fields(document(raw)))
    birth = result["fields"]["date_of_birth"]
    assert birth.value == birth.normalized_value == expected
    assert birth.raw == birth.observed_value == raw
    assert birth.display_value != raw
    assert birth.validation["birth_century_rule_applied"] is True
    assert birth.status == "uncertain"
    assert result["mrz"].fields["date_of_birth"] == raw
    expiry = result["fields"]["date_of_expiry"]
    assert expiry.value == expiry.normalized_value == "1930-04-15"
    assert expiry.raw == "300415"
    assert "date_of_issue" not in result["fields"]


@pytest.mark.parametrize("raw", ["", "04112", "0411237", "04<123", "010229", "261301", "270231"])
def test_invalid_birth_reading_is_not_made_into_a_date(raw):
    assert normalize_mrz_date_century(raw) is None


def test_printed_full_birth_year_overrides_the_century_rule_and_other_dates_stay_printed():
    result = prepare_output(extract_fields([
        row("Date of Birth: 01 JAN 1926", 0),
        row("Date of Issue: 01 FEB 2020", 60),
        row("Date of Expiry: 15 APR 2030", 120),
        *document("260101"),
    ]))
    fields = result["fields"]
    assert fields["date_of_birth"].normalized_value == "1926-01-01"
    assert not fields["date_of_birth"].validation.get("birth_century_rule_applied")
    assert fields["date_of_issue"].normalized_value == "2020-02-01"
    assert fields["date_of_expiry"].normalized_value == "2030-04-15"
    assert not fields["date_of_expiry"].validation.get("expiry_century_rule_applied")


def test_birth_from_unchecked_mrz_stays_uncertain_after_formatting():
    rows = document("620801")
    rows[1].text = rows[1].text[:-1] + str((int(rows[1].text[-1]) + 1) % 10)
    result = prepare_output(extract_fields(rows))
    assert not result["mrz"].checksum_valid
    birth = result["fields"]["date_of_birth"]
    assert birth.display_value == "01-August-1962"
    assert birth.status == "uncertain"
    assert "MRZ validation failed" in birth.reason


@pytest.mark.parametrize("raw,expected,display", [
    ("000229", "2000-02-29", "29-February-2000"),
    ("261231", "2026-12-31", "31-December-2026"),
    ("270101", "1927-01-01", "01-January-1927"),
    ("300415", "1930-04-15", "15-April-1930"),
    ("930903", "1993-09-03", "03-September-1993"),
    ("991231", "1999-12-31", "31-December-1999"),
])
def test_expiry_rule_reaches_output_preserving_source_and_issue_date(raw, expected, display):
    result = prepare_output(extract_fields([
        row("Date of Issue: 01 FEB 2020", 0), *document("620801", raw),
    ]))
    expiry = result["fields"]["date_of_expiry"]
    assert expiry.value == expiry.normalized_value == expected
    assert expiry.display_value == display
    assert expiry.raw == expiry.observed_value == raw
    assert expiry.validation["expiry_century_rule_applied"] is True
    assert expiry.status == "uncertain"
    assert result["mrz"].fields["date_of_expiry"] == raw
    assert result["fields"]["date_of_issue"].normalized_value == "2020-02-01"
    assert not result["fields"]["date_of_issue"].validation.get("expiry_century_rule_applied")


def test_invalid_mrz_expiry_is_not_formatted():
    expiry = prepare_output(extract_fields(document("620801", "270231")))["fields"]["date_of_expiry"]
    assert expiry.normalized_value is None
    assert expiry.value is None


def test_expiry_from_unchecked_mrz_stays_uncertain():
    rows = document("620801", "930903")
    rows[1].text = rows[1].text[:-1] + str((int(rows[1].text[-1]) + 1) % 10)
    expiry = prepare_output(extract_fields(rows))["fields"]["date_of_expiry"]
    assert expiry.display_value == "03-September-1993"
    assert expiry.status == "uncertain"
    assert "MRZ validation failed" in expiry.reason


def test_century_rule_keeps_expiry_before_birth_visible_as_a_warning():
    result = prepare_output(extract_fields(document("620801", "300415")))
    assert result["fields"]["date_of_expiry"].normalized_value == "1930-04-15"
    assert result["fields"]["date_of_expiry"].validation["birth_on_or_before_expiry"] is False
