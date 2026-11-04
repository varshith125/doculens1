import pytest

from app.extractors.field_extractor import extract_fields
from app.extractors.label_matcher import is_caption, match_label
from app.schemas.models import OCRLine


def row(text, x, y, width, height=9):
    return OCRLine(text=text, confidence=0.95, bounding_box=[
        [x, y], [x + width, y], [x + width, y + height], [x, y + height],
    ])


@pytest.mark.parametrize("damaged", [
    "Doto of BirtyDoto de Naissance", "Dato of Birth", "Date of Issual",
])
def test_damaged_date_heading_is_not_appended_to_name(damaged):
    lines = [row("Given Names", 114, 92, 69, 8), row("ALEX", 114, 99, 26),
             row(damaged, 115, 110, 94, 7), row("01 AUG/AOUT 62", 114, 116, 70)]
    field = extract_fields(lines)["fields"]["given_names"]
    assert field.value == "ALEX"
    assert field.observed_value == "ALEX"
    assert all(damaged not in item.raw_text for item in field.evidence)
    assert lines[2].text == damaged  # Transcript remains intact for review.


def test_damaged_heading_is_only_a_boundary_not_an_invented_label():
    damaged = "Doto of BirtyDoto de Naissance"
    assert match_label(damaged) is None
    assert is_caption(damaged)
    fields = extract_fields([row(damaged, 0, 0, 200), row("01 AUG 1962", 0, 15, 100)])["fields"]
    assert "date_of_birth" not in fields


@pytest.mark.parametrize("name", ["MORGAN", "DE SILVA", "DOTO", "DOTO DE SILVA", "DATE", "DATO"])
def test_names_are_still_allowed_as_wrapped_lines(name):
    assert not is_caption(name)
    field = extract_fields([row("Given Names", 0, 0, 100), row("ALEX", 0, 10, 50),
                            row(name, 0, 20, 100)])["fields"]["given_names"]
    assert field.value == "ALEX " + name
