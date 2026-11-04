import pytest

from app.extractors.field_extractor import extract_fields
from app.schemas.models import OCRLine, OCRObservation


def line(text, y=200, confidence=0.74, observations=()):
    return OCRLine(text=text, confidence=confidence, review_required=bool(observations),
                   observations=list(observations),
                   bounding_box=[[0, y], [440, y], [440, y + 18], [0, y + 18]])


def rows(prefix="P<", alternate_prefix="P<", complete=True):
    raw = (prefix + "INDDOE<CALEX<<<<C").ljust(44, "<")
    other = (alternate_prefix + "INDDOE<<ALEX<<<<C").ljust(44, "<")
    first = line(raw, observations=[
        OCRObservation(text=raw, confidence=0.74, method="initial"),
        OCRObservation(text=other, confidence=0.76, method="crop"),
    ])
    return [first] + ([line("L898902C36UTO7408122F1204159ZE184226B<<<<<10", 225, 0.98)] if complete else [])


@pytest.mark.parametrize("complete", [True, False])
def test_agreeing_passport_prefix_supplies_code_despite_damaged_names(complete):
    result = extract_fields(rows(complete=complete))
    field = next(f for f in result["other_fields"] if f.field_name == "document_code")
    assert field.value == "P"
    assert field.value_kind == "mrz"
    assert field.status == "uncertain"
    assert field.validation["mrz_document_code_agreement"] is True
    assert not result["mrz"].checksum_valid


@pytest.mark.parametrize("prefix", ["I<", "PA"])
def test_conflicting_document_prefix_is_not_silently_selected(prefix):
    result = extract_fields(rows(alternate_prefix=prefix))
    field = next(f for f in result["other_fields"] if f.field_name == "document_code")
    assert field.value is None


def test_clear_printed_code_stays_primary():
    result = extract_fields([line("Type: PD", 0, 0.99), *rows()])
    field = next(f for f in result["other_fields"] if f.field_name == "document_code")
    assert field.value == "PD"
    assert field.value_kind == "printed"
    assert field.validation["source_agreement"] is False


def test_one_weak_reading_is_not_enough_for_prefix_fallback():
    first = rows()[0].model_copy(update={"observations": []})
    result = extract_fields([first, rows()[1]])
    field = next(f for f in result["other_fields"] if f.field_name == "document_code")
    assert field.value is None


def test_two_character_passport_code_is_preserved():
    result = extract_fields(rows(prefix="PA", alternate_prefix="PA"))
    field = next(f for f in result["other_fields"] if f.field_name == "document_code")
    assert field.value == "PA"
