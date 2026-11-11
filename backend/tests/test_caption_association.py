"""Synthetic association regressions; no document images or private identities."""

from app.extractors.caption_context import prepare_captions
from app.extractors.field_extractor import extract_fields, merge_field
from app.extractors.label_matcher import match_label
from app.patterns.common import known_country_code
from app.schemas.models import FieldValue, OCRLine


def row(text, x=0, y=0, width=180, height=10, side="front"):
    return OCRLine(text=text, confidence=0.99, side=side, bounding_box=[
        [x, y], [x + width, y], [x + width, y + height], [x, y + height],
    ])


def test_first_given_middle_and_generic_name_are_not_collapsed():
    fields = extract_fields([
        row("First Name: ALEX", y=0), row("Middle Name: MORGAN", y=70),
        row("Surname: EXAMPLE", y=140), row("Name: EXAMPLE ALEX MORGAN", y=210),
    ])["fields"]
    assert fields["first_name"].value == "ALEX"
    assert "given_names" not in fields
    assert fields["middle_names"].value == "MORGAN"
    assert fields["surname"].value == "EXAMPLE"
    assert fields["full_name"].display_label == "Name"
    assert fields["full_name"].value == "EXAMPLE ALEX MORGAN"


def test_split_caption_keeps_original_fragments_and_boxes():
    lines = [row("Given", width=35), row("Names", x=40, width=35),
             row("ALEX MORGAN", y=20, height=18)]
    field = extract_fields(lines)["fields"]["given_names"]
    assert field.value == "ALEX MORGAN"
    assert [part.raw_text for part in field.evidence[0].label_fragments] == ["Given", "Names"]
    assert field.evidence[0].label_fragments[1].bounding_box == lines[1].bounding_box
    assert [line.text for line in lines] == ["Given", "Names", "ALEX MORGAN"]


def test_split_caption_never_joins_opposite_sides():
    fields = extract_fields([
        row("Given", width=35), row("Names", x=40, width=35, side="back"),
        row("ALEX", y=20, height=18),
    ])["fields"]
    assert fields["given_names"].value is None


def test_noisy_prefix_needs_document_and_caption_size_context():
    heading = "Na tionalité zz Nationality"
    lines = [row(heading, width=230), row("FRENCH", y=20, height=18),
             row("Surname: EXAMPLE", x=300, y=0),
             row("Given Names: ALEX", x=300, y=70),
             row("Date of Birth: 12 AUG 1988", x=300, y=140)]
    field = extract_fields(lines)["fields"]["nationality"]
    assert field.value == "FRENCH"
    assert field.status == "uncertain"
    assert field.display_label == heading
    assert field.evidence[0].label_fragments[0].raw_text == heading
    assert "nationality" not in extract_fields(lines[:2])["fields"]


def test_wrapped_name_does_not_jump_over_a_missed_heading():
    field = extract_fields([
        row("Name", width=50), row("ALEX", y=15, height=18),
        row("Natt0na1!ty", y=35, height=7), row("INDIAN", y=44, height=18),
    ])["fields"]["full_name"]
    assert field.value == "ALEX"


def test_country_word_can_be_a_printed_name():
    assert extract_fields([row("Name: INDIA")])["fields"]["full_name"].value == "INDIA"


def test_country_code_and_nationality_remain_separate():
    result = extract_fields([
        row("Country Code: UTO"), row("Issuing Country: UTOPIA", y=70),
        row("Nationality: INDIAN", y=140),
    ])
    assert result["fields"]["country_code"].value == "UTO"
    assert result["fields"]["issuing_country"].value == "UTOPIA"
    assert result["fields"]["nationality"].value == "INDIAN"
    assert result["issuing_country"] == "UTO"


def test_name_translation_fragment_is_not_a_value():
    matched = match_label("Name + Nonn •")
    assert matched is not None
    assert matched.field_name == "full_name"
    assert matched.value == ""


def test_three_dates_keep_their_roles_and_representations():
    fields = extract_fields([
        row("Date of Birth: 12 AUG 1988"),
        row("Date of Issue: 12th November 2024", y=70),
        row("Date of Expiry: 11.11.2034", y=140),
    ], date_order="dmy")["fields"]
    assert fields["date_of_birth"].display_value == "12-August-1988"
    assert fields["date_of_issue"].display_value == "12-November-2024"
    assert fields["date_of_expiry"].display_value == "11-November-2034"
    assert fields["date_of_issue"].observed_value == "12th November 2024"
    assert fields["date_of_issue"].normalized_value == "2024-11-12"


def test_mrz_comparison_preserves_meaningful_name_boundaries():
    printed = FieldValue(field_name="given_names", value="ANN ABEL", value_kind="printed",
                         source="visual", status="detected", confidence=0.99)
    mrz = FieldValue(field_name="given_names", value="ANNA BEL", value_kind="mrz",
                     source="mrz", status="detected", confidence=0.99)
    result = merge_field(printed, mrz)
    assert result.value == "ANN ABEL"
    assert result.status == "conflicting"
    assert result.validation["source_agreement"] is False


def test_separate_translation_boxes_form_one_caption_with_source_fragments():
    lines = [row("Name", width=40), row("/ Nom", x=45, width=50),
             row("ALEX MORGAN", y=20, height=18)]
    fields = extract_fields(lines)["fields"]
    assert fields["full_name"].value == "ALEX MORGAN"
    assert "surname" not in fields
    assert fields["full_name"].display_label == "Name / Nom"
    assert [part.raw_text for part in fields["full_name"].evidence[0].label_fragments] == [
        "Name", "/ Nom",
    ]
    assert lines[0].text == "Name" and lines[1].text == "/ Nom"


def test_translation_join_does_not_combine_different_field_headings():
    fields = extract_fields([
        row("Surname", width=60), row("/ Given Names", x=70, width=100),
        row("EXAMPLE", y=20, width=60, height=18),
        row("ALEX", x=70, y=20, width=60, height=18),
    ])["fields"]
    assert fields["surname"].value == "EXAMPLE"
    assert fields["given_names"].value == "ALEX"


def test_damaged_translated_heading_is_not_an_inline_country_value():
    fields = extract_fields([
        row("Issuing Country / Issuing countrv", width=250),
        row("Canada", y=20, height=18),
    ])["fields"]
    field = fields["issuing_country"]
    assert field.value == "Canada"
    assert field.observed_value == "Canada"
    assert field.normalized_value == "CAN"
    assert field.validation["approximate_label_match"] is True
    assert field.evidence[0].associated_label == "Issuing Country / Issuing countrv"
    assert match_label("Nationality / French").value == "French"


def test_local_country_database_does_not_infer_nationality_from_issuer():
    fields = extract_fields([
        row("Country Code: CAN"), row("Nationality: Peru", y=70),
        row("Name: CANADA", y=140),
    ])["fields"]
    assert fields["country_code"].normalized_value == "CAN"
    assert fields["nationality"].value == "Peru"
    assert fields["nationality"].normalized_value == "PER"
    assert fields["full_name"].value == "CANADA"
    assert known_country_code("Canada / CAN") == "CAN"
    assert known_country_code("Canada / Peru") is None
    assert known_country_code("CANADAX") is None
    assert known_country_code("Côte d'Ivoire") == "CIV"


def test_translation_join_requires_same_side_and_printed_separator():
    opposite = [row("Name", width=40), row("/ Nom", x=45, width=50, side="back")]
    separate = [row("Name", width=40), row("Surname", x=45, width=70)]
    for lines in (opposite, separate):
        prepared, sources = prepare_captions(lines)
        assert len(prepared) == 2
        assert not sources
