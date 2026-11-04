import pytest

from app.extractors.field_extractor import extract_fields
from app.patterns.dates import normalize_date
from app.schemas.models import OCRLine
from app.services.output import prepare_output


def issue(raw, order="dmy", caption="Date of Issue"):
    row = OCRLine(text=f"{caption}: {raw}", confidence=0.99,
                  bounding_box=[[0, 0], [700, 0], [700, 25], [0, 25]])
    return prepare_output(extract_fields([row], date_order=order))["fields"][
        {"Date of Issue": "date_of_issue", "Date of Birth": "date_of_birth",
         "Date of Expiry": "date_of_expiry"}[caption]]


@pytest.mark.parametrize("raw,iso", [
    ("03 SEP/SEPT 93", "1993-09-03"), ("23-11-04", "2004-11-23"),
    ("01/01/26", "2026-01-01"), ("01/01/27", "1927-01-01"),
    ("29 FEB 00", "2000-02-29"), ("31 DEC 99", "1999-12-31"),
    ("231104", "2004-11-23"), ("SEP 03, 93", "1993-09-03"),
    ("03SEP93", "1993-09-03"), ("٠٣/٠٩/٩٣", "1993-09-03"),
])
def test_two_digit_issue_year_reaches_output(raw, iso):
    field = issue(raw)
    assert field.value == field.normalized_value == iso
    assert field.raw == field.observed_value == raw
    assert field.display_value != raw
    assert field.validation["issue_century_rule_applied"] is True
    assert field.status == "uncertain"


@pytest.mark.parametrize("raw", ["31/02/24", "29 FEB 01", "03 SEP/OCT 93", "??/??/93", "930903"])
def test_invalid_or_incomplete_issue_dates_are_not_forced_into_a_date(raw):
    field = issue(raw)
    assert field.normalized_value is None
    assert not field.validation.get("issue_century_rule_applied")


def test_issue_date_order_is_respected():
    assert issue("03/04/24", "auto").normalized_value is None
    assert issue("03/04/24", "dmy").normalized_value == "2024-04-03"
    assert issue("03/04/24", "mdy").normalized_value == "2024-03-04"
    assert issue("030424", "auto").normalized_value is None


@pytest.mark.parametrize("raw,iso", [("01 JAN 1926", "1926-01-01"), ("03 SEP 2093", "2093-09-03")])
def test_four_digit_issue_year_is_preserved(raw, iso):
    field = issue(raw)
    assert field.normalized_value == iso
    assert not field.validation.get("issue_century_rule_applied")


@pytest.mark.parametrize("caption", ["Date of Birth", "Date of Expiry"])
def test_issue_change_does_not_expand_other_printed_dates(caption):
    assert issue("03 SEP 93", caption=caption).normalized_value is None
    assert normalize_date("03 SEP 93")[1] is not None
