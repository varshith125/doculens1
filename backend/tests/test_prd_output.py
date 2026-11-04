import pytest

from app.extractors.field_extractor import extract_fields
from app.schemas.models import OCRLine
from app.services.output import prepare_output


def row(text, y):
    return OCRLine(text=text, confidence=0.98,
                   bounding_box=[[0, y], [500, y], [500, y + 20], [0, y + 20]])


def test_prd_names_dates_and_nationality_preserve_originals():
    result = prepare_output(extract_fields([
        row("Given Names: Alex James", 0), row("Nationality: Indian", 60),
        row("Date of Birth: 12 AUG 1988", 120),
    ]))
    fields = result["fields"]
    assert fields["given_names"].value == "ALEX JAMES"
    assert fields["given_names"].raw == "Alex James"
    assert fields["date_of_birth"].value == "1988-08-12"
    assert fields["date_of_birth"].raw == "12 AUG 1988"
    assert fields["nationality"].code == "IND"
    assert fields["nationality"].validation["iso_country_code"] is True


def test_unresolved_date_does_not_masquerade_as_iso_date():
    result = prepare_output(extract_fields([row("Date of Birth: 12 AUG 88", 0)]))
    field = result["fields"]["date_of_birth"]
    assert field.value is None
    assert field.raw == "12 AUG 88"
    assert field.status == "uncertain"


@pytest.mark.parametrize("raw,iso,display", [
    ("25 mar 2005", "2005-03-25", "25-March-2005"),
    ("25-4-2021", "2021-04-25", "25-April-2021"),
    ("25th April 2021", "2021-04-25", "25-April-2021"),
])
@pytest.mark.parametrize("caption,key", [
    ("Date of Birth", "date_of_birth"),
    ("Date of Issue", "date_of_issue"),
    ("Date of Expiry", "date_of_expiry"),
])
def test_date_display_is_consistent_without_changing_source(raw, iso, display, caption, key):
    field = prepare_output(extract_fields([row(f"{caption}: {raw}", 0)]))["fields"][key]
    assert field.value == field.normalized_value == iso
    assert field.display_value == display
    assert field.raw == raw
