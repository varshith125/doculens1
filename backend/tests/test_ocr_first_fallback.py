"""OCR-first field selection, independently safe MRZ names and translated labels."""

import pytest

from app.extractors.field_extractor import extract_fields
from app.extractors.mrz_parser import parse_mrz
from app.schemas.models import OCRLine
from app.services.output import prepare_output


def row(text, y=0, confidence=0.99, review=False):
    return OCRLine(text=text, confidence=confidence, review_required=review,
                   bounding_box=[[0, y], [700, y], [700, y + 18], [0, y + 18]])


def mrz(names="EXAMPLE<<ALEX<MORGAN", confidence=0.99, review=False):
    return [row("P<UTO" + names.ljust(39, "<"), 400, confidence, review),
            row("L898902C36UTO7408122F1204159ZE184226B<<<<<10", 425)]


def output(lines):
    return prepare_output(extract_fields(lines, date_order="dmy"))


@pytest.mark.parametrize("names,agreement", [
    ("DIFFERENT<<SOMEONE<ELSE", False),
    ("EXAMPLE<<ALEX<MORGAN", True),
])
def test_clear_printed_names_are_cross_checked_without_replacing_ocr(names, agreement):
    result = output([row("Surname: EXAMPLE"), row("Given names: ALEX MORGAN", 80), *mrz(names)])
    for key, expected in (("surname", "EXAMPLE"), ("given_names", "ALEX MORGAN")):
        field = result["fields"][key]
        assert field.value == expected
        assert field.value_kind == "printed"
        assert field.source == "visual"
        assert field.status == "detected"
        assert field.validation["source_agreement"] is agreement
        assert {e.source for e in field.evidence} == {"visual", "mrz"}
    assert result["checks"]["mrz_matches_printed"] is agreement
    assert result["mrz"].raw_lines == [r.text for r in mrz(names)]


@pytest.mark.parametrize("caption,key,expected", [
    ("Passport number: X12345678", "document_number", "X12345678"),
    ("Nationality: Indian", "nationality", "Indian"),
    ("Date of birth: 12 AUG 1988", "date_of_birth", "1988-08-12"),
    ("Sex: M", "sex", "M"),
])
def test_other_clear_printed_fields_also_ignore_mrz_disagreement(caption, key, expected):
    result = output([row(caption), *mrz()])
    field = result["fields"][key]
    assert field.value == expected
    assert field.value_kind == "printed"
    assert field.source == "visual"
    assert field.status != "conflicting"
    assert isinstance(field.validation.get("source_agreement"), bool)


@pytest.mark.parametrize("bad_surname,confidence,review", [
    ("", 0.99, False), ("EXAMPLF", 0.45, False),
    ("EXAMPLF", 0.99, True), ("EXAMP1E", 0.99, False),
    ("<<<<<CCCCCC", 0.99, False),
])
def test_fallback_changes_only_the_unreadable_component(bad_surname, confidence, review):
    result = output([row("Surname: " + bad_surname, confidence=confidence, review=review),
                     row("Given names: PRINTED NAME", 80), *mrz()])
    surname = result["fields"]["surname"]
    given = result["fields"]["given_names"]
    assert surname.value == "EXAMPLE"
    assert surname.value_kind == "mrz"
    assert surname.validation["mrz_fallback"] is True
    assert given.value == "PRINTED NAME"
    assert given.source == "visual"
    assert given.validation["source_agreement"] is False


@pytest.mark.parametrize("names", ["EXAMPLE<<CCCCCC", "EXAMPLE<<C<C<C", "EXAMPLE<<ALEX<<<CCC"])
def test_damaged_mrz_given_name_is_not_output(names):
    result = output([row("Surname: PRINTED"), row("Given names:", 80), *mrz(names)])
    assert result["fields"]["surname"].value == "PRINTED"
    assert result["fields"]["given_names"].value is None
    assert "full_name" not in result["fields"]
    assert result["mrz"].raw_lines[0] == mrz(names)[0].text


def test_damaged_surname_does_not_destroy_independent_given_names():
    result = output([*mrz("CCCCCC<<ALEX")])
    assert not result["fields"].get("surname")
    assert result["fields"]["given_names"].value == "ALEX"


def test_damaged_separator_cannot_merge_given_names_into_surname():
    result = output(mrz("EXAMPLE<CTESTPERSON<<<<C"))
    assert "surname" not in result["fields"]
    assert "given_names" not in result["fields"]
    assert result["mrz"].raw_lines


@pytest.mark.parametrize("names,surname,given", [
    ("MCCARTHY<<CECIL", "MCCARTHY", "CECIL"),
    ("COCCO<<C<ALAN", "COCCO", "C ALAN"),
    ("DE<SILVA<<ANNA<MARIA", "DE SILVA", "ANNA MARIA"),
])
def test_genuine_c_letters_initials_and_multiple_names_are_preserved(names, surname, given):
    parsed = parse_mrz([r.text for r in mrz(names)])
    assert parsed.fields["surname"] == surname
    assert parsed.fields["given_names"] == given


@pytest.mark.parametrize("caption,key,heading", [
    ("अन्य भाषा / Surname: Gummadi", "surname", "Surname"),
    ("अन्य भाषा / First name: Gummadi", "first_name", "First Name"),
    ("Surname / unfamiliar translation: Gummadi", "surname", "Surname"),
    ("Nom / Surname: Gummadi", "surname", "Surname"),
    ("Voornamen / Given names: Alex Morgan", "given_names", "Given Names"),
])
def test_translated_caption_is_never_the_name(caption, key, heading):
    field = output([row(caption)])["fields"][key]
    assert field.value == caption.split(":")[-1].strip().upper()
    assert field.display_label == heading
    assert field.evidence[0].associated_label == caption


def test_first_name_stays_first_name_and_cross_checks_first_mrz_token():
    field = output([row("First name: PRINTED"), *mrz("EXAMPLE<<OTHER<PERSON")])["fields"]["first_name"]
    assert field.value == "PRINTED"
    assert field.source == "visual"
    assert field.validation["source_agreement"] is False


def test_single_mrz_given_name_can_fill_an_explicit_missing_first_name():
    fields = output([row("First name:"), *mrz("EXAMPLE<<ALEX")])["fields"]
    assert fields["first_name"].value == "ALEX"
    assert fields["first_name"].value_kind == "mrz"
    assert "given_names" not in fields


def test_multiple_mrz_given_names_are_not_guessed_into_first_and_middle_names():
    fields = output([row("First name:"), *mrz()])["fields"]
    assert fields["first_name"].value is None
    assert fields["given_names"].value == "ALEX MORGAN"
    assert "middle_names" not in fields


@pytest.mark.parametrize("confidence,review", [(0.4, False), (0.99, True)])
def test_unclear_mrz_cannot_replace_a_missing_name(confidence, review):
    fields = output([row("Surname:"), *mrz(confidence=confidence, review=review)])["fields"]
    assert fields["surname"].value is None


def test_no_clear_source_keeps_name_unreadable_instead_of_guessing():
    field = output([row("Surname: EXAMP1E")])["fields"]["surname"]
    assert field.value is None
    assert field.raw == "EXAMP1E"


def test_unknown_translation_label_uses_the_separate_name_value():
    field = output([row("Surname / unfamiliar translation"), row("GUMMADI", 25)])["fields"]["surname"]
    assert field.value == "GUMMADI"
    assert field.display_label == "Surname"


def test_damaged_caption_does_not_replace_a_clear_separate_value():
    heading = row("Surname / unfamiliar translation", review=True)
    result = output([heading, row("PRINTED", 25), *mrz()])
    field = result["fields"]["surname"]
    assert field.value == "PRINTED"
    assert field.source == "visual"
    assert field.validation["value_ocr_review_required"] is False
