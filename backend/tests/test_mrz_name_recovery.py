import numpy as np
import pytest

from app.extractors.field_extractor import extract_fields
from app.extractors.mrz_parser import detect_mrz, parse_mrz
from app.schemas.models import OCRLine, OCRObservation
from app.services.ocr import OCRService


def row(text, observations=(), confidence=0.91):
    return OCRLine(text=text, confidence=confidence, review_required=bool(observations),
                   observations=list(observations),
                   bounding_box=[[0, 200], [440, 200], [440, 220], [0, 220]])


def observation(text, method, confidence=0.93, field_name=None, box=None):
    return OCRObservation(text=text, confidence=confidence, method=method,
                          field_name=field_name, bounding_box=box)


@pytest.mark.parametrize("prefix", ["P<IND", "P<IND<"])
def test_passport_names_follow_issuer_and_explicit_separator(prefix):
    text = prefix + "GUMMADI<<VARSHITH"
    parsed, _ = detect_mrz([row(text)])
    assert parsed.fields["surname"] == "GUMMADI"
    assert parsed.fields["given_names"] == "VARSHITH"
    assert parsed.raw_lines == [text]
    assert not parsed.checksum_valid


def test_extra_filler_does_not_claim_full_mrz_validation():
    first = ("P<UTO<ERIKSSON<<ANNA<MARIA").ljust(44, "<")
    result = parse_mrz([first, "L898902C36UTO7408122F1204159ZE184226B<<<<<10"])
    assert result.fields["surname"] == "ERIKSSON"
    assert result.fields["given_names"] == "ANNA MARIA"
    assert not result.checksum_valid


def test_missing_separator_requires_an_actual_delimited_reread():
    raw = "P<INDDOE<CALEX<<<<C".ljust(44, "<")
    clean = "P<INDDOE<<ALEX".ljust(44, "<")
    unresolved = extract_fields([row(raw)])
    assert not unresolved["fields"].get("surname")
    assert not unresolved["fields"].get("given_names")
    recovered = extract_fields([row(raw, [observation(raw, "original"),
                                         observation(clean, "cubic"), observation(clean, "linear")])])
    for name, value in [("surname", "DOE"), ("given_names", "ALEX")]:
        field = recovered["fields"][name]
        assert field.value == value
        assert field.status == "uncertain"
        assert field.validation["mrz_name_recovered"]
    assert recovered["mrz"].raw_lines == [raw]
    assert not recovered["mrz"].checksum_valid


def test_single_confident_reread_does_not_invent_a_name():
    raw = "P<INDCCCCCC<<CCCCCC".ljust(44, "<")
    clean = "P<INDOTHER<<PERSON".ljust(44, "<")
    result = extract_fields([row(raw, [observation(clean, "one crop", 0.99)])])
    assert not result["fields"].get("surname")
    assert not result["fields"].get("given_names")


def test_disagreeing_component_crops_do_not_choose_a_spelling():
    raw = "P<INDDOE<<ALFX<<<C".ljust(44, "<")
    readings = [observation("ALEX", "linear", 0.98, "given_names"),
                observation("ALFX", "cubic", 0.99, "given_names")]
    result = extract_fields([row(raw, readings)])
    assert not result["fields"].get("given_names")


def test_clear_name_row_skips_additional_model_calls():
    line = row("P<INDDOE<<ALEX".ljust(44, "<"), confidence=0.99)
    def unexpected_call(*args, **kwargs):
        pytest.fail("Clear MRZ names should not incur extra model calls")
    OCRService._retry_mrz_names(unexpected_call, np.zeros((240, 500, 3), dtype=np.uint8), [line])
    assert not line.observations


def test_recovered_mrz_name_does_not_replace_clear_printed_name():
    raw = "P<INDDOE<CALEX<<<<C".ljust(44, "<")
    clean = "P<INDDOE<<ALEX".ljust(44, "<")
    printed = OCRLine(text="Surname: PRINTED", confidence=0.99,
                      bounding_box=[[0, 0], [300, 0], [300, 20], [0, 20]])
    result = extract_fields([printed, row(raw, [observation(clean, "cubic"),
                                               observation(clean, "linear")])])
    surname = result["fields"]["surname"]
    assert surname.value == "PRINTED"
    assert surname.value_kind == "printed"
    assert surname.validation["source_agreement"] is False


def test_component_crop_recovery_retains_alternatives_and_its_own_box():
    raw = "P<INDDOE<<ALFX<<<C".ljust(44, "<")
    box = [[100, 200], [150, 200], [150, 220], [100, 220]]
    readings = [observation(raw, "initial"),
                observation("ALEX", "name linear", 0.98, "given_names", box),
                observation("ALEX", "name cubic", 0.91, "given_names", box)]
    field = extract_fields([row(raw, readings)])["fields"]["given_names"]
    assert field.value == "ALEX"
    assert field.status == "uncertain"
    assert any(e.raw_text == raw for e in field.evidence)
    assert any(e.raw_text == "ALEX" and e.bounding_box == box for e in field.evidence)


@pytest.mark.parametrize("mrz_given,agrees", [("JOHN<JOSEPH", True), ("OTHER<PERSON", False)])
def test_combined_printed_names_are_compared_with_mrz_not_themselves(mrz_given, agrees):
    lines = [OCRLine(text=text, confidence=0.99,
                     bounding_box=[[0, y], [440, y], [440, y + 18], [0, y + 18]])
             for text, y in [("Given names: JOHN", 0), ("Middle name: JOSEPH", 40),
                             (("P<UTODOE<<" + mrz_given).ljust(44, "<"), 200),
                             ("L898902C36UTO7408122F1204159ZE184226B<<<<<10", 225)]]
    field = extract_fields(lines)["fields"]["given_names"]
    assert field.value == "JOHN"
    assert field.validation["source_agreement"] is agrees
