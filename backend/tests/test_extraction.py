import pytest

from app.extractors.field_extractor import extract_fields
from app.extractors.label_matcher import match_label
from app.extractors.mrz_parser import check_digit
from app.patterns.dates import normalize_date
from app.patterns.emirates_id import find_emirates_ids, normalize_emirates_id
from app.patterns.passports import passport_number_matches
from app.schemas.models import OCRLine


def line(text, x=0, y=0, width=200, confidence=0.99, side="front"):
    return OCRLine(
        text=text,
        confidence=confidence,
        bounding_box=[[x, y], [x + width, y], [x + width, y + 20], [x, y + 20]],
        side=side,
    )


def mrz_lines(side="front", number="L898902C3"):
    first = "P<UTOEXAMPLE<<TEST<<<<<<<<<<<<<<<<<<<<<<<<<<<"
    first = first[:44].ljust(44, "<")
    second = number + check_digit(number) + "UTO7408122F3004157" + "<" * 14 + "0"
    # The date check digit is calculated rather than coupled to a fixture string.
    second = second[:27] + check_digit(second[21:27]) + second[28:]
    second += check_digit(second[:10] + second[13:20] + second[21:43])
    return [line(first, y=500, width=800, side=side), line(second, y=530, width=800, side=side)]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2025-12-31", "2025-12-31"),
        ("31/12/2025", "2025-12-31"),
        ("12/31/2025", "2025-12-31"),
        ("12 AUG 1974", "1974-08-12"),
        ("12 AUG/AOUT 1974", "1974-08-12"),
        ("AUG 12, 1974", "1974-08-12"),
    ],
)
def test_date_normalization(value, expected):
    assert normalize_date(value) == (expected, None)


@pytest.mark.parametrize(
    "value", ["01/02/2025", "31/02/2025", "12 AUG 74", "740812", "29 FEB 1900", "12 AUG/SEP 1974"]
)
def test_uncertain_dates_preserve_printed_value(value):
    normalized, reason = normalize_date(value)
    assert normalized == value
    assert reason


@pytest.mark.parametrize(
    "label,name,value",
    [
        ("Surname: EXAMPLE", "surname", "EXAMPLE"),
        ("Family Name", "surname", ""),
        ("Nationality / Nationalité: UTO", "nationality", "UTO"),
        ("Date of Birth: 12 AUG 1974", "date_of_birth", "12 AUG 1974"),
        ("رقم الهوية: 784-2000-1234567-1", "emirates_id_number", "784-2000-1234567-1"),
    ],
)
def test_label_aliases(label, name, value):
    result = match_label(label)
    assert result.field_name == name
    assert result.value == value


@pytest.mark.parametrize("text", ["Nationalityish", "Some Surname EXAMPLE", "NAMELESS", "passport"])
def test_label_substrings_not_accepted(text):
    assert match_label(text) is None


def test_spatial_label_value_association():
    result = extract_fields(
        [
            line("Surname", width=100),
            line("EXAMPLE", y=25),
            line("Given Names", x=350, width=150),
            line("TEST", x=350, y=25),
        ]
    )
    assert result["fields"]["surname"].value == "EXAMPLE"
    assert result["fields"]["given_names"].value == "TEST"


def test_does_not_jump_across_intervening_label():
    result = extract_fields(
        [line("Surname", width=100), line("Nationality", y=25, width=100), line("UTO", y=50)]
    )
    assert "surname" not in result["fields"]
    assert result["fields"]["nationality"].value == "UTO"


def test_distant_value_and_opposite_side_are_not_matched():
    result = extract_fields(
        [line("Surname"), line("DISTANT", x=800, y=300), line("OTHER SIDE", y=25, side="back")]
    )
    assert "surname" not in result["fields"]


def test_labels_are_never_values():
    result = extract_fields([line("Surname"), line("Given names", y=25), line("Nationality", y=50)])
    assert result["fields"] == {}


def test_does_not_guess_meaning_of_unlabelled_date_or_number():
    result = extract_fields([line("12 AUG 1974"), line("A12345678", y=40)])
    assert result["fields"] == {}


@pytest.mark.parametrize("value", ["784200012345671", "784-2000-1234567-1", "784 2000 1234567 1"])
def test_emirates_id_format(value):
    assert normalize_emirates_id(value) == "784200012345671"
    assert find_emirates_ids("ID Number: " + value) == ["784200012345671"]


@pytest.mark.parametrize(
    "value", ["78420001234567", "7842000123456712", "999200012345671", "A784200012345671"]
)
def test_reject_partial_or_embedded_emirates_id(value):
    assert normalize_emirates_id(value) is None
    assert find_emirates_ids(value) == []


def test_no_birthdate_inferred_from_emirates_id():
    result = extract_fields([line("784-2000-1234567-1")])
    assert result["document_type"] == "emirates_id"
    assert "date_of_birth" not in result["fields"]
    assert result["issuing_country"] is None
    assert result["fields"]["emirates_id_number"].status == "detected"


def test_front_back_conflicts_preserve_evidence():
    result = extract_fields([line("Surname: EXAMPLE"), line("Surname: DIFFERENT", side="back")])
    field = result["fields"]["surname"]
    assert field.value == "EXAMPLE"
    assert field.status == "conflicting"
    assert {item.side for item in field.evidence} == {"front", "back"}


def test_matching_front_back_values_are_merged():
    result = extract_fields([line("Surname: EXAMPLE"), line("Surname: Example", side="back")])
    field = result["fields"]["surname"]
    assert field.value == "EXAMPLE"
    assert field.status == "detected"
    assert len(field.evidence) == 2


def test_low_confidence_and_ambiguous_dates_uncertain():
    result = extract_fields(
        [line("Surname: EXAMPLE", confidence=0.40), line("Date of Birth: 01/02/2000", y=40)]
    )
    assert result["fields"]["surname"].status == "uncertain"
    assert result["fields"]["date_of_birth"].status == "uncertain"


def test_mrz_names_not_validated_and_birth_century_uses_fixed_rule():
    result = extract_fields(mrz_lines())
    assert result["mrz"].checksum_valid
    assert result["fields"]["document_number"].status == "validated"
    assert result["fields"]["surname"].status == "detected"
    assert result["fields"]["date_of_birth"].value == "1974-08-12"
    assert result["fields"]["date_of_birth"].observed_value == "740812"
    assert result["fields"]["date_of_expiry"].value == "1930-04-15"
    assert result["fields"]["date_of_expiry"].normalized_value == "1930-04-15"
    assert result["fields"]["date_of_birth"].status == "uncertain"
    assert "date_of_issue" not in result["fields"]


def test_printed_date_resolves_mrz_century_without_guessing():
    result = extract_fields([
        line("Date of Birth: 12 AUG 1974"), line("Date of Expiry: 15 APR 2030", y=50),
        *mrz_lines(),
    ])
    field = result["fields"]["date_of_birth"]
    assert field.value == "1974-08-12"
    assert field.status == "detected"
    assert field.source == "visual"


def test_visual_reading_is_kept_without_cross_checking_mrz():
    result = extract_fields([line("Passport No: X12345678")] + mrz_lines())
    field = result["fields"]["document_number"]
    assert field.value == "X12345678"
    assert any("X12345678" in item.raw_text for item in field.evidence)
    assert field.status == "detected"
    assert "source_agreement" not in field.validation
    assert result["mrz"].raw_lines


def test_opposite_side_mrz_conflict_is_exposed():
    result = extract_fields(mrz_lines() + mrz_lines(side="back", number="A12345678"))
    assert result["fields"]["document_number"].status == "conflicting"
    assert result["mrz"].checksum_valid is False
    assert any("different MRZ" in item for item in result["warnings"])


def test_additional_fields_and_missing_text():
    result = extract_fields([line("Occupation: TESTER")])
    assert result["other_fields"][0].value == "TESTER"
    assert extract_fields([])["fields"] == {}


def test_unconfigured_printed_caption_preserved_as_other_field():
    result = extract_fields([line("Card version: FOUR")])
    assert result["other_fields"][0].field_name == "card_version"
    assert result["other_fields"][0].evidence[0].raw_text == "Card version: FOUR"


@pytest.mark.parametrize(
    "value,country,expected",
    [
        ("123456789", "GBR", True),
        ("A12345678", "GBR", False),
        ("A12345678", "USA", True),
        ("123456789", "USA", True),
        ("1234567", "USA", False),
        ("A1234567", "IND", None),
    ],
)
def test_country_specific_patterns(value, country, expected):
    assert passport_number_matches(value, country) is expected


def test_date_cross_field_validation():
    result = extract_fields(
        [line("Date of Issue: 2030-01-01"), line("Expiry Date: 2029-01-01", y=40)]
    )
    assert result["fields"]["date_of_issue"].status == "uncertain"
    assert result["fields"]["date_of_expiry"].status == "uncertain"


@pytest.mark.parametrize("inline", [True, False])
def test_wrapped_name_is_one_value_with_original_fragments(inline):
    # Fictional long name: a line wrap must not become a conflict.
    rows = (
        [line("Name: ALEX MORGAN EXAMPLE", width=480)]
        if inline
        else [line("Full Name", width=100), line("ALEX MORGAN EXAMPLE", y=25, width=480)]
    )
    offset = 25 if inline else 50
    rows += [line("TESTPERSON", y=offset), line("Nationality: India", y=offset + 30)]
    result = extract_fields(rows)
    name = result["fields"]["full_name"]
    assert name.value == "ALEX MORGAN EXAMPLE TESTPERSON"
    assert name.status == "detected"
    assert len(name.evidence) == 2
    assert result["fields"]["nationality"].value == "India"


def test_name_continuation_does_not_cross_next_caption_or_side():
    result = extract_fields(
        [
            line("Name: ALEX", width=400),
            line("Nationality", y=25, width=90),
            line("India", x=100, y=25),
            line("OTHER", y=25, side="back"),
        ]
    )
    assert result["fields"]["full_name"].value == "ALEX"


def test_conflict_shows_highest_confidence_and_keeps_all_evidence():
    result = extract_fields(
        [
            line("Name: FIRST", confidence=0.85),
            line("Name: SECOND", confidence=0.99, side="back"),
            line("Name: THIRD", confidence=0.9, y=200),
        ]
    )
    field = result["fields"]["full_name"]
    assert field.value == "SECOND"
    assert field.confidence == 0.99
    assert field.status == "conflicting"
    assert len(field.evidence) == 3


@pytest.mark.parametrize(
    "value", ["03 / 04 / 1990", "03-04-1990", "03.04.1990", "03 04 1990", "٠٣/٠٤/١٩٩٠"]
)
def test_explicit_dmy_dates(value):
    assert normalize_date(value, "dmy") == ("1990-04-03", None)


def test_explicit_mdy_and_invalid_date_remain_distinct():
    assert normalize_date("03/04/1990", "mdy") == ("1990-03-04", None)
    assert normalize_date("31/02/1990", "dmy")[1]
    assert normalize_date("12/31/1990", "dmy")[1]


def test_dotted_caption_and_combined_row():
    result = extract_fields([line("D. O. B. 03 / 04 / 1990 Sex: M")], date_order="dmy")
    assert result["fields"]["date_of_birth"].value == "1990-04-03"
    assert result["fields"]["sex"].value == "M"


def test_bilingual_label_prefix():
    assert match_label("नाम / Surname: EXAMPLE").value == "EXAMPLE"


def test_reread_pattern_is_not_promoted_to_detected():
    row = line("784-2000-1234567-1")
    row.review_required = True
    row.recognition_note = "Rereads differed."
    assert extract_fields([row])["fields"]["emirates_id_number"].status == "uncertain"


def test_format_checks_do_not_erase_number_conflicts():
    result = extract_fields(
        [
            line("PASSPORT"),
            line("Issuing Country: GBR", y=60),
            line("Passport No: X12345678", y=100),
            line("Passport No: 123456789", side="back", confidence=0.9),
        ]
    )
    number = result["fields"]["document_number"]
    assert number.value == "X12345678"
    assert number.status == "conflicting"
    assert len(number.evidence) == 2


@pytest.mark.parametrize("reverse", [False, True])
def test_overlapping_name_boxes_with_caption_between_baselines(reverse):
    # Same geometry as a two-row ID name, with fictional text and overlapping OCR padding.
    rows = [
        OCRLine(
            text="ALEX MORGAN EXAMPLE LONGNAME",
            confidence=0.996,
            bounding_box=[[288, 217], [649, 217], [649, 241], [288, 241]],
        ),
        OCRLine(
            text="Name:",
            confidence=0.999,
            bounding_box=[[226, 224], [289, 224], [289, 251], [226, 251]],
        ),
        OCRLine(
            text="TESTPERSON",
            confidence=0.999,
            bounding_box=[[289, 236], [372, 236], [372, 261], [289, 261]],
        ),
        line("Date of Birth:", x=229, y=265, width=114),
        line("22/07/1982", x=406, y=256, width=111),
    ]
    name = extract_fields(list(reversed(rows)) if reverse else rows)["fields"]["full_name"]
    assert name.value == "ALEX MORGAN EXAMPLE LONGNAME TESTPERSON"
    assert name.status == "detected"
    assert len(name.evidence) == 2


@pytest.mark.parametrize(
    "caption,field",
    [
        ("Surname/Nom/Apellidos", "surname"),
        ("Given names/Prénoms/Nombres", "given_names"),
        ("Passport No./No. du Passeport/No.de Pasaporte", "document_number"),
        ("Nationality/Nationalité/Nacionalidad", "nationality"),
        ("Sex/Sexe/Sexo", "sex"),
        ("Date of birth/Date de naissance/Fecha de nacimiento", "date_of_birth"),
        ("Date of expiration/Date d'expiration/Fecha de caducidad", "date_of_expiry"),
    ],
)
def test_multilingual_captions_are_not_field_values(caption, field):
    match = match_label(caption)
    assert match.field_name == field
    assert match.value == ""


def test_centered_date_below_a_wide_caption():
    result = extract_fields(
        [
            line("Issuing Date /", x=226, y=337, width=211),
            line("22/08/2025", x=297, y=364, width=90),
        ],
        date_order="dmy",
    )
    assert result["fields"]["date_of_issue"].value == "2025-08-22"


def test_full_name_assembled_without_losing_original_components():
    fields = extract_fields(
        [
            line("Surname/Nom/Apellidos"),
            line("EXAMPLE", y=25),
            line("Given names/Prénoms/Nombres", y=65),
            line("ALEX MORGAN", y=90),
        ]
    )["fields"]
    assert fields["surname"].value == "EXAMPLE"
    assert fields["given_names"].value == "ALEX MORGAN"
    assert fields["full_name"].value == "ALEX MORGAN EXAMPLE"
    assert fields["full_name"].source == "assembled"


def test_existing_full_name_keeps_its_printed_order():
    fields = extract_fields(
        [
            line("Full name: EXAMPLE ALEX"),
            line("Surname: EXAMPLE", y=80),
            line("Given names: ALEX", y=120),
        ]
    )["fields"]
    assert fields["full_name"].value == "EXAMPLE ALEX"


def test_missing_surname_is_not_invented_from_given_names():
    fields = extract_fields([line("Given names: ALEX MORGAN")])["fields"]
    assert fields["given_names"].value == "ALEX MORGAN"
    assert "surname" not in fields


def test_slanted_security_text_is_not_a_nationality_candidate():
    rows = [
        line("Nationality", x=400, y=100, width=200),
        line("UNITED STATES OF AMERICA", x=400, y=125, width=260),
        OCRLine(
            text="EPLURIBUS",
            confidence=0.99,
            bounding_box=[[610, 70], [700, 125], [685, 150], [595, 95]],
        ),
    ]
    field = extract_fields(rows)["fields"]["nationality"]
    assert field.value == "UNITED STATES OF AMERICA"
    assert field.status == "detected"


def test_compact_named_date_preserves_full_year():
    assert normalize_date("10JUN 1965") == ("1965-06-10", None)
    assert normalize_date("06JAN2024") == ("2024-01-06", None)
