import math

import pytest

from app.extractors.field_extractor import extract_fields
from app.schemas.models import OCRLine


def row(text, x, y, width, angle):
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    return OCRLine(
        text=text,
        confidence=0.96,
        bounding_box=[
            [px * cosine - py * sine, px * sine + py * cosine]
            for px, py in [(x, y), (x + width, y), (x + width, y + 20), (x, y + 20)]
        ],
    )


@pytest.mark.parametrize("angle", [-18, -11, 0, 11, 18])
def test_tilted_parallel_name_columns_preserve_fields_and_source_boxes(angle):
    rows = [
        row("Surname", 0, 0, 180, angle),
        row("EXAMPLE", 0, 30, 110, angle),
        row("Given Names", 300, 0, 170, angle),
        row("ALEX MORGAN", 300, 30, 210, angle),
    ]
    original_boxes = [[point[:] for point in line.bounding_box] for line in rows]
    fields = extract_fields(rows)["fields"]
    assert fields["surname"].value == "EXAMPLE"
    assert fields["given_names"].value == "ALEX MORGAN"
    assert [line.bounding_box for line in rows] == original_boxes
    assert fields["given_names"].evidence[0].bounding_box == rows[3].bounding_box


@pytest.mark.parametrize("angle", [-15, 15])
def test_tilted_wrapped_name_does_not_absorb_next_caption(angle):
    rows = [
        row("Name: ALEX MORGAN", 100, 100, 300, angle),
        row("EXAMPLE", 120, 130, 130, angle),
        row("Nationality: India", 100, 180, 300, angle),
    ]
    fields = extract_fields(rows)["fields"]
    assert fields["full_name"].value == "ALEX MORGAN EXAMPLE"
    assert fields["nationality"].value == "India"


def test_garbled_translation_suffix_does_not_hide_printed_date_below():
    rows = [
        row("Issuing Date /Y", 225, 337, 211, 0),
        row("15/06/2020", 296, 365, 91, 0),
        row("Expiry Date", 225, 395, 211, 0),
        row("14/06/2030", 296, 423, 91, 0),
    ]
    fields = extract_fields(rows, date_order="dmy")["fields"]
    assert fields["date_of_issue"].value == "2020-06-15"
    assert fields["date_of_expiry"].value == "2030-06-14"


def test_invalid_inline_date_does_not_silently_use_another_nearby_date():
    rows = [row("Issuing Date: 35/19/2020", 225, 337, 211, 0), row("15/06/2020", 296, 365, 91, 0)]
    field = extract_fields(rows, date_order="dmy")["fields"]["date_of_issue"]
    assert field.value == "35/19/2020"
    assert field.status == "uncertain"
