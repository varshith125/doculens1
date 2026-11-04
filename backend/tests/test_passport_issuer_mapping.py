"""Synthetic OCR/layout regressions, not an OCR accuracy benchmark on real passports."""
import pytest

from app.extractors.field_extractor import extract_fields
from app.extractors.label_matcher import match_label
from app.extractors.mrz_parser import parse_mrz
from app.schemas.models import OCRLine
from app.services.output import prepare_output


def row(text, x=0, y=0, width=170, height=14, confidence=0.98, side="front"):
    return OCRLine(text=text, confidence=confidence, side=side,
                   bounding_box=[[x, y], [x + width, y], [x + width, y + height], [x, y + height]])


def mrz(issuer="IND", nationality="IND"):
    return [
        "P<" + issuer.ljust(3, "<") + "EXAMPLE<<ALEX".ljust(39, "<"),
        "L898902C36" + nationality.ljust(3, "<") + "7408122F1204159ZE184226B<<<<<10",
    ]


def mrz_rows(issuer="IND", nationality="IND"):
    return [row(text, y=400 + i * 24, width=600, height=20)
            for i, text in enumerate(mrz(issuer, nationality))]


def output(lines):
    result = prepare_output(extract_fields(lines))
    return result, {**result["fields"], **{f.field_name: f for f in result["other_fields"]}}


@pytest.mark.parametrize("caption,key", [
    ("Issuing Country", "issuing_country"), ("Country of Issue", "issuing_country"),
    ("Issuing State", "issuing_country"), ("Pays émetteur", "issuing_country"),
    ("País de expedición", "issuing_country"), ("دولة الإصدار", "issuing_country"),
    ("Issuing Country Code", "country_code"), ("Country Code", "country_code"),
    ("Code du pays", "country_code"), ("Issuing Authority", "issuing_authority"),
    ("Authority", "issuing_authority"), ("Autorité de délivrance", "issuing_authority"),
    ("Ausstellende Behörde", "issuing_authority"), ("جهة الإصدار", "issuing_authority"),
    ("Authority Code", "authority_code"), ("Issuing Authority Code", "authority_code"),
    ("Code de l'autorité", "authority_code"), ("رمز جهة الإصدار", "authority_code"),
    ("Nationality", "nationality"), ("Nationalité", "nationality"),
    ("Place of Issue", "place_of_issue"), ("Lieu de délivrance", "place_of_issue"),
    ("مكان الإصدار", "place_of_issue"),
])
def test_label_meanings_stay_distinct(caption, key):
    label = match_label(caption)
    assert label and label.field_name == key and label.value == ""


@pytest.mark.parametrize("country,code,authority,nationality,place,labels", [
    ("India", "IND", "Passport Office, Hyderabad", "Indian", "Hyderabad",
     ["Country of Issue", "Country Code", "Authority", "Nationality", "Place of Issue"]),
    ("United Arab Emirates", "ARE", "Federal Authority for Identity and Citizenship", "Emirati", "Abu Dhabi",
     ["دولة الإصدار", "رمز دولة الاصدار", "جهة الإصدار", "الجنسية", "مكان الإصدار"]),
    ("United States", "USA", "United States Department of State", "American", "Washington",
     ["Issuing Country", "Issuing Country Code", "Issuing Authority", "Nationality", "Issued at"]),
    ("United Kingdom", "GBR", "HMPO", "British Citizen", "London",
     ["Issuing State", "Country Code", "Authority", "Nationality", "Place of Issue"]),
    ("Canada", "CAN", "Passport Canada", "Canadian", "Ottawa",
     ["Pays émetteur / Issuing Country", "Code du pays / Country Code", "Autorité / Authority",
      "Nationalité / Nationality", "Lieu de délivrance / Place of Issue"]),
    ("Germany", "D", "Stadt Berlin", "Deutsch", "Berlin",
     ["Ausstellender Staat", "Ländercode", "Ausstellende Behörde", "Staatsangehörigkeit", "Ausstellungsort"]),
])
@pytest.mark.parametrize("arrangement", ["columns", "inline", "stacked"])
def test_international_layouts_keep_all_printed_fields(country, code, authority, nationality, place, labels, arrangement):
    values = [country, code, authority, nationality, place, "AB-123"]
    captions = labels + ["Authority Code"]
    lines = [row("PASSPORT", y=-50)]
    for index, (caption, value) in enumerate(zip(captions, values, strict=True)):
        x, y = ((index % 3) * 350, (index // 3) * 90) if arrangement == "columns" else (0, index * 60)
        if arrangement == "inline":
            lines.append(row(f"{caption}: {value}", x, y, width=600))
        else:
            lines.extend([row(caption, x, y), row(value, x, y + 20, width=280, height=18)])
    _, fields = output(lines + mrz_rows(code, code))
    for key, value in zip(
        ["issuing_country", "country_code", "issuing_authority", "nationality", "place_of_issue", "authority_code"], values, strict=True,
    ):
        field = fields[key]
        assert field.value == value, (key, field)
        assert field.status != "conflicting", (key, field)
        assert field.raw == value
    assert fields["nationality"].code == code
    assert fields["issuing_authority"].source == "visual"
    assert fields["authority_code"].source == "visual"


def test_mrz_issuer_does_not_supply_office_or_place_or_nationality():
    result, fields = output(mrz_rows("USA", "VNM"))
    assert fields["issuing_country"].value == "United States"
    assert fields["country_code"].value == "USA"
    assert fields["nationality"].code == "VNM"
    assert fields["issuing_authority"].value is None
    assert fields["authority_code"].value is None
    assert "place_of_issue" not in fields
    assert result["mrz"].fields["document_code"] == "P"
    assert result["mrz"].fields["issuing_country"] == "USA"


def test_printed_country_is_kept_without_mrz_cross_check():
    result, fields = output([row("Country of Issue: India"), *mrz_rows("USA", "IND")])
    assert fields["issuing_country"].value == "India"
    assert fields["issuing_country"].status == "detected"
    assert fields["country_code"].value == "USA"
    assert fields["country_code"].status != "conflicting"
    assert result["checks"]["mrz_matches_printed"] is None
    assert {e.source for e in fields["issuing_country"].evidence} == {"visual"}


def test_printed_code_conflict_does_not_overwrite_print():
    _, fields = output([row("Country Code: IND"), *mrz_rows("USA", "IND")])
    assert fields["country_code"].value == "IND"
    assert fields["country_code"].status == "detected"


def test_printed_nationality_is_independent_of_mrz_and_issuer():
    _, fields = output([row("Nationality: Indian"), *mrz_rows("USA", "VNM")])
    assert fields["nationality"].value == "Indian"
    assert fields["nationality"].status == "detected"
    assert fields["country_code"].value == "USA"
    assert fields["country_code"].status != "conflicting"


@pytest.mark.parametrize("code", ["ZZZ", "US", "DEU", "XXA"])
def test_unknown_or_nonissuer_mrz_code_cannot_be_selected(code):
    result, fields = output(mrz_rows(code, "IND"))
    assert result["mrz"].checks["issuing_country_code_known"] is False
    assert fields["issuing_country"].value is None
    assert fields["country_code"].value is None
    assert fields["country_code"].raw == code
    assert fields["nationality"].code == "IND"


@pytest.mark.parametrize("issuer,nationality", [("D", "D"), ("UNO", "XXA"), ("RKS", "GBN"), ("UTO", "UTO")])
def test_icao_exceptions_are_preserved(issuer, nationality):
    parsed = parse_mrz(mrz(issuer, nationality))
    assert parsed.checks["issuing_country_code_known"] is True
    assert parsed.checks["nationality_code_known"] is True
    _, fields = output(mrz_rows(issuer, nationality))
    assert fields["country_code"].value == issuer
    assert fields["nationality"].code == nationality


def test_ambiguous_shared_value_is_not_assigned_to_two_headings():
    _, fields = output([
        # Overlapping detector boxes leave equal support for both headings.
        row("Issuing Country", width=110), row("Nationality", x=40, width=110),
        row("India", x=20, y=20, width=100),
    ])
    assert fields["issuing_country"].value is None
    assert fields["nationality"].value is None


def test_country_label_does_not_take_closer_department_value():
    _, fields = output([
        row("Country of Issue", width=180),
        row("Department of State", x=190, y=0, width=200),
        row("USA", y=25, width=80),
    ])
    assert fields["issuing_country"].value == "United States"


def test_adjacent_authority_code_and_country_code_do_not_share_values():
    _, fields = output([
        row("Authority Code", width=100), row("Country Code", x=160, width=100),
        row("HYD-01", y=20, width=85), row("IND", x=160, y=20, width=45),
    ])
    assert fields["authority_code"].value == "HYD-01"
    assert fields["country_code"].value == "IND"


def test_unqualified_code_does_not_guess_its_meaning():
    _, fields = output([row("Code: HYD"), *mrz_rows()])
    assert fields["country_code"].value == "IND"
    assert fields["authority_code"].value is None


def test_low_confidence_authority_stays_under_its_label_for_review():
    _, fields = output([row("Authority: HMPO", confidence=0.5), *mrz_rows("GBR", "GBR")])
    assert fields["issuing_authority"].value == "HMPO"
    assert fields["issuing_authority"].status == "uncertain"


def test_country_code_label_cannot_accept_country_name_or_office():
    _, fields = output([row("Country Code: Passport Office, Hyderabad")])
    assert fields["country_code"].value is None


def test_arabic_label_can_own_a_value_on_its_left():
    _, fields = output([
        row("جهة الإصدار", x=200, width=130), row("مكتب دبي", x=60, width=120),
        row("رمز دولة الإصدار", x=200, y=70, width=130), row("ARE", x=140, y=70, width=40),
    ])
    assert fields["issuing_authority"].value == "مكتب دبي"
    assert fields["country_code"].value == "ARE"


def test_arabic_association_cannot_cross_another_heading():
    _, fields = output([
        row("جهة الإصدار", x=200, width=100),
        row("الجنسية", x=120, width=70), row("IND", x=70, width=40),
    ])
    assert fields["issuing_authority"].value is None
    assert fields["nationality"].value == "IND"


def test_arabic_country_wording_and_nationality_remain_independent():
    _, fields = output([
        row("دولة الإصدار: الإمارات العربية المتحدة"), row("الجنسية: الهندية", y=80),
        *mrz_rows("ARE", "IND"),
    ])
    assert fields["issuing_country"].value == "United Arab Emirates"
    assert fields["issuing_country"].status != "conflicting"
    assert fields["nationality"].value == "الهندية"
    assert fields["nationality"].code == "IND"
    assert fields["nationality"].status != "conflicting"


def test_output_normalization_is_repeatable_for_special_icao_codes():
    result, _ = output(mrz_rows("UNO", "XXA"))
    before = {key: field.model_dump() for key, field in result["fields"].items()}
    prepare_output(result)
    assert {key: field.model_dump() for key, field in result["fields"].items()} == before


def test_office_name_starting_with_authority_is_a_value():
    _, fields = output([
        row("Issuing Authority"), row("Authority for Identity and Citizenship", y=20, width=300),
    ])
    assert fields["issuing_authority"].value == "Authority for Identity and Citizenship"


def test_wrapped_authority_stops_at_next_printed_label():
    _, fields = output([
        row("Issuing Authority"), row("Passport Office,", y=20, height=18),
        row("Hyderabad", y=42, height=18),
        row("Place of Issue", y=64), row("Secunderabad", y=84, height=18),
    ])
    assert fields["issuing_authority"].value == "Passport Office, Hyderabad"
    assert fields["place_of_issue"].value == "Secunderabad"


@pytest.mark.parametrize("parts,key,value", [
    (["Authority", "Code"], "authority_code", "HYD-01"),
    (["Issuing Country", "Code"], "country_code", "IND"),
    (["Issuing", "Country", "Code"], "country_code", "IND"),
    (["Issuing", "Authority", "Code"], "authority_code", "HYD-01"),
])
def test_split_code_captions_keep_the_longer_meaning(parts, key, value):
    lines = [row(part, x=index * 105, width=100) for index, part in enumerate(parts)]
    _, fields = output([*lines, row(value, y=30, width=100)])
    assert fields[key].value == value
    assert fields[key].evidence[0].label_fragments
    assert "issuing_authority" not in fields
    assert "issuing_country" not in fields


def test_bare_code_caption_is_not_an_authority_value():
    _, fields = output([row("Authority", width=80), row("Code", x=100, width=60),
                        row("IND", x=100, y=20, width=60)])
    assert fields.get("issuing_authority") is None or fields["issuing_authority"].value is None
