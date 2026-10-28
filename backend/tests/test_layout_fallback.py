import pytest

from app.extractors.field_extractor import extract_fields
from app.patterns.dates import normalize_date
from app.schemas.models import OCRLine


def row(text, x, y, width=120):
    return OCRLine(
        text=text,
        confidence=0.96,
        bounding_box=[[x, y], [x + width, y], [x + width, y + 20], [x, y + 20]],
    )


def passport_rows():
    return [
        row("REPUBLIC OF INDIA", 155, 20, 300),
        row("IND", 270, 50, 30),
        row("EXAMPLE", 200, 115),
        row("ALEX MORGAN", 200, 145),
        row("21011961", 200, 175),
        row("M", 360, 175, 20),
        row("TESTCITY, TESTSTATE", 200, 205),
        row("TESTCITY", 200, 235),
        row("03/04/2020", 200, 265),
        row("03/04/2030", 200, 295),
        row("P<INDEXAMPLE<<ALEX<MORGAN<C<<C<<<<<<<<<<", 20, 350, 540),
    ]


def test_corroborated_layout_fields_are_named_but_remain_uncertain():
    result = extract_fields(passport_rows(), date_order="dmy")
    fields = result["fields"]
    assert result["document_type"] == "passport"
    assert fields["given_names"].value == "ALEX MORGAN"
    assert fields["surname"].value == "EXAMPLE"
    assert fields["full_name"].value == "ALEX MORGAN EXAMPLE"
    assert fields["date_of_birth"].value == "1961-01-21"
    assert fields["date_of_issue"].value == "2020-04-03"
    assert fields["date_of_expiry"].value == "2030-04-03"
    assert all(field.status == "uncertain" for field in fields.values())
    assert "document_number" not in fields
    assert "nationality" not in fields  # Issuing state is not evidence of nationality.
    assert result["mrz"].checksum_valid is not True


def test_disagreeing_blurred_names_are_not_filled_from_partial_mrz():
    rows = passport_rows()
    rows[2].text = "EXAMPLF"
    rows[3].text = "ALEX M0RGAN"
    # Preserve a letter-only OCR reading, as the profile requires plausible text rows.
    rows[3].text = "ALEX MCRGAN"
    fields = extract_fields(rows, date_order="dmy")["fields"]
    assert fields["surname"].value is None
    assert fields["given_names"].value is None
    assert "full_name" not in fields
    assert any("EXAMPLF" in item.raw_text for item in fields["surname"].evidence)


@pytest.mark.parametrize("bad_date", ["1961110112", "218011961", "25/15/2025", "21/01/0016"])
def test_layout_keeps_invalid_dates_unreadable_with_raw_evidence(bad_date):
    rows = passport_rows()
    rows[4].text = bad_date
    field = extract_fields(rows, date_order="dmy")["fields"]["date_of_birth"]
    assert field.value is None
    assert field.status == "uncertain"
    assert field.evidence[0].raw_text == bad_date


@pytest.mark.parametrize(
    "mutation", ["no_country", "no_mrz", "wrong_country", "different_side", "two_mrzs"]
)
def test_layout_requires_document_and_spatial_anchors(mutation):
    rows = passport_rows()
    if mutation == "no_country":
        rows = rows[2:]
    elif mutation == "no_mrz":
        rows = rows[:-1]
    elif mutation == "wrong_country":
        rows[-1].text = rows[-1].text.replace("P<IND", "P<UTO")
    elif mutation == "different_side":
        rows[-1].side = "back"
    else:
        rows.append(row(rows[-1].text, 20, 400, 540))
    assert "date_of_birth" not in extract_fields(rows, date_order="dmy")["fields"]


def test_compact_date_requires_explicit_order_and_valid_calendar():
    assert normalize_date("21011961", "dmy") == ("1961-01-21", None)
    assert normalize_date("01211961", "mdy") == ("1961-01-21", None)
    assert normalize_date("21011961", "auto")[1]
    assert normalize_date("31021961", "dmy")[1]


def test_user_name_example_preserves_field_boundaries():
    fields = extract_fields(
        [row("Given Name: VENKATA VARSHITH", 0, 0, 400), row("Surname: GUMMADI", 0, 60, 300)]
    )["fields"]
    assert fields["given_names"].value == "VENKATA VARSHITH"
    assert fields["surname"].value == "GUMMADI"
    assert fields["full_name"].value == "VENKATA VARSHITH GUMMADI"


def test_middle_name_is_separate_and_full_name_is_never_split():
    fields = extract_fields(
        [
            row("First Name: ALEX", 0, 0),
            row("Middle Name: MORGAN", 0, 60),
            row("Last Name: EXAMPLE", 0, 120),
        ]
    )["fields"]
    assert fields["given_names"].value == "ALEX"
    assert fields["given_names"].display_label == "First Name"
    assert fields["middle_names"].value == "MORGAN"
    assert fields["middle_names"].display_label == "Middle Name"
    assert fields["surname"].value == "EXAMPLE"
    assert fields["surname"].display_label == "Last Name"
    assert fields["full_name"].value == "ALEX MORGAN EXAMPLE"
    fields = extract_fields([row("Full Name: ALEX MORGAN EXAMPLE", 0, 0, 400)])["fields"]
    assert set(fields) == {"full_name"}
