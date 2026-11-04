"""Synthetic document-routing cases. No private documents or OCR calls."""

import pytest

from app.extractors.field_extractor import extract_fields
from app.extractors.mrz_parser import check_digit
from app.schemas.models import OCRLine


def row(text, y=0, confidence=0.99, side="front", width=500):
    return OCRLine(text=text, confidence=confidence, side=side, bounding_box=[
        [0, y], [width, y], [width, y + 18], [0, y + 18],
    ])


def emirates_rows(number="784-2000-0000000-1", confidence=0.99):
    return [
        row("UNITED ARAB EMIRATES"), row("Resident Identity Card", 60),
        row("ID Number: " + number, 120, confidence),
        row("Name: ALEX MORGAN EXAMPLE", 180),
        row("Nationality: INDIAN", 240), row("Date of Birth: 12 AUG 1988", 300),
        row("Issuing Date: 12/11/2024", 360), row("Expiry Date: 11/11/2034", 420),
    ]


def td1(side="back"):
    number, birth, expiry = "A00000001", "880812", "341111"
    first = "I<ARE" + number + check_digit(number) + "<" * 15
    second = birth + check_digit(birth) + "M" + expiry + check_digit(expiry) + "IND" + "<" * 11
    second += check_digit(first[5:30] + second[:7] + second[8:15] + second[18:29])
    return [row(text, 500 + index * 27, side=side, width=800) for index, text in enumerate([
        first, second, "EXAMPLE<<ALEX<MORGAN".ljust(30, "<"),
    ])]


@pytest.mark.parametrize("number,confidence", [
    ("784-2000-0000000-1", 0.99), ("784-2000-0000000-1", 0.55),
    ("784-2000-000000-1", 0.99), ("784-20OO-0000000-1", 0.99),
])
def test_emirates_id_without_mrz_keeps_printed_fields_even_with_uncertain_number(number, confidence):
    result = extract_fields(emirates_rows(number, confidence), date_order="dmy")
    assert result["document_type"] == "emirates_id"
    assert not result["mrz"].detected
    assert result["mrz"].fields == {}
    assert result["fields"]["emirates_id_number"].observed_value == number
    assert "national_id_number" not in result["fields"]
    assert result["fields"]["full_name"].value == "ALEX MORGAN EXAMPLE"
    assert result["fields"]["nationality"].value == "INDIAN"
    assert result["fields"]["date_of_birth"].display_value == "12-August-1988"
    assert result["fields"]["date_of_issue"].display_value == "12-November-2024"
    assert result["fields"]["date_of_expiry"].display_value == "11-November-2034"
    assert "document_number" not in result["fields"]
    if confidence < 0.8 or number != "784-2000-0000000-1":
        assert result["fields"]["emirates_id_number"].status == "uncertain"


def test_missing_emirates_id_value_does_not_change_its_heading_or_document_type():
    result = extract_fields([row("EMIRATES ID"), row("ID Number", 60), row("Name: ALEX", 120)])
    assert result["document_type"] == "emirates_id"
    assert result["fields"]["emirates_id_number"].value is None
    assert "national_id_number" not in result["fields"]


def test_generic_id_with_passport_reference_is_not_classified_as_passport():
    result = extract_fields([
        row("NATIONAL IDENTITY CARD"), row("Passport Number: AB0000001", 60),
        row("ID Number: 00001234", 120), row("Name: ALEX EXAMPLE", 180),
        row("Nationality: UNITED ARAB EMIRATES", 240),
    ])
    assert result["document_type"] == "identity_card"
    assert result["fields"]["national_id_number"].value == "00001234"
    assert "emirates_id_number" not in result["fields"]
    assert "configured_passport_format" not in result["fields"]["document_number"].validation


def test_unlabelled_nationality_value_is_not_an_issuer_heading():
    result = extract_fields([
        row("NATIONAL IDENTITY CARD"), row("Nationality", 60),
        row("UNITED ARAB EMIRATES", 82), row("ID Number: 00001234", 150),
    ])
    assert result["document_type"] == "identity_card"
    assert "emirates_id_number" not in result["fields"]


def test_uae_passport_keeps_passport_classification_with_an_id_number_field():
    result = extract_fields([
        row("UNITED ARAB EMIRATES"), row("PASSPORT", 60),
        row("Passport Number: A0000001", 120), row("ID Number: 784-2000-0000000-1", 180),
    ])
    assert result["document_type"] == "passport"
    assert "national_id_number" in result["fields"]


def test_separately_labeled_card_number_is_not_reused_as_emirates_id():
    result = extract_fields([
        row("EMIRATES ID"), row("Card Number", 60), row("784-2000-0000000-1", 82),
    ])
    assert "emirates_id_number" not in result["fields"]
    card = next(field for field in result["other_fields"] if field.field_name == "card_number")
    assert card.value == "784-2000-0000000-1"


def test_id_mrz_document_number_does_not_override_a_separate_passport_number():
    result = extract_fields(emirates_rows() + [row("Passport No: ZZ0000001", 450)] + td1())
    assert result["document_type"] == "emirates_id"
    assert result["mrz"].format == "TD1"
    assert result["fields"]["document_number"].value == "ZZ0000001"
    assert result["fields"]["emirates_id_number"].value == "784200000000001"
    mrz_number = next(field for field in result["other_fields"] if field.field_name == "mrz_document_number")
    assert mrz_number.value == "A00000001"


def test_passport_without_mrz_keeps_printed_dates_and_number():
    result = extract_fields([
        row("PASSPORT"), row("Passport Number: Z0000001", 60),
        row("Surname: EXAMPLE", 120), row("Given Names: ALEX", 180),
        row("Date of Birth: 12 AUG 1988", 240),
    ])
    assert result["document_type"] == "passport"
    assert not result["mrz"].detected
    assert result["fields"]["document_number"].value == "Z0000001"
    assert result["fields"]["date_of_birth"].display_value == "12-August-1988"


def test_printed_title_with_subtitle_is_independent_of_mrz_checksum():
    result = extract_fields([row("PASSPORT – TRAVEL DOCUMENT SPECIMEN"), row("Surname: EXAMPLE", 70)])
    assert result["document_type"] == "passport"
    assert extract_fields([row("Instructions for passport – read carefully")])["document_type"] == "unknown"


def test_incomplete_mrz_does_not_erase_readable_identity_fields():
    lines = emirates_rows() + [row("I<ARE000000001<<<<<<<<<<<<<<", 500, side="back", width=800)]
    result = extract_fields(lines, date_order="dmy")
    assert result["document_type"] == "emirates_id"
    assert result["mrz"].raw_lines
    assert result["mrz"].fields == {}
    assert result["fields"]["full_name"].value == "ALEX MORGAN EXAMPLE"


def test_conflicting_document_titles_request_review():
    result = extract_fields(emirates_rows() + [row("PASSPORT", side="back")])
    assert result["document_type"] == "unknown"
    assert "different document types" in result["document_type_reason"]
    assert result["warnings"]


def test_passport_mrz_on_an_id_is_preserved_without_injecting_passport_fields():
    number, birth, expiry = "Z00000001", "880812", "341111"
    first = "P<UTO" + "OTHER<<PERSON".ljust(39, "<")
    second = number + check_digit(number) + "UTO" + birth + check_digit(birth)
    second += "M" + expiry + check_digit(expiry) + "<" * 14 + "0"
    second += check_digit(second[:10] + second[13:20] + second[21:43])
    result = extract_fields(emirates_rows() + [
        row(first, 500, side="back", width=800), row(second, 527, side="back", width=800),
    ])
    assert result["document_type"] == "emirates_id"
    assert result["mrz"].raw_lines == [first, second]
    assert result["fields"]["full_name"].value == "ALEX MORGAN EXAMPLE"
    assert "document_number" not in result["fields"]
    assert "surname" not in result["fields"]
    assert any("not merged" in warning for warning in result["warnings"])
