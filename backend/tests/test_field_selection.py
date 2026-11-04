import pytest

from app.extractors.field_extractor import merge_field
from app.schemas.models import Evidence, FieldValue


def reading(value, source="visual", status="detected", confidence=0.94):
    return FieldValue(
        field_name="document_number",
        value=value,
        source=source,
        value_kind="printed" if source == "visual" else "mrz",
        status=status,
        confidence=confidence,
        evidence=[Evidence(source=source, raw_text=value or "Unreadable")],
    )


def test_printed_value_wins_without_hiding_mrz_conflict():
    visual = reading("A12345678")
    mrz = reading("A12345670", "mrz", "validated", 0.999)
    for first, second in ((visual, mrz), (mrz, visual)):
        selected = merge_field(first, second)
        assert selected.value == visual.value
        assert selected.status == "conflicting"
        assert selected.selection_basis == "labeled_print"
        assert len(selected.evidence) == 2
        assert selected.model_dump()["selection_basis"] == "labeled_print"


def test_readable_print_is_not_overwritten_just_because_it_requires_review():
    selected = merge_field(
        reading("A12345670", status="uncertain"),
        reading("A12345678", "mrz", "validated", 0.90),
    )
    assert selected.value == "A12345670"
    assert selected.status == "conflicting"
    assert selected.selection_basis == "labeled_print"


def test_selection_provenance_survives_agreement_then_later_disagreement():
    selected = merge_field(reading("A12345678"), reading("A12345678", "mrz", "validated"))
    selected = merge_field(selected, reading("A12345670", "mrz", "validated", 1))
    assert selected.value == "A12345678"
    assert selected.status == "conflicting"
    assert selected.selection_basis == "labeled_print"
    assert len(selected.evidence) == 3


def test_unreadable_candidate_evidence_is_retained():
    selected = merge_field(reading(None, status="uncertain"), reading("A12345678"))
    assert selected.value == "A12345678"
    assert len(selected.evidence) == 2


@pytest.mark.parametrize("name", ["date_of_birth", "date_of_expiry"])
@pytest.mark.parametrize("mrz_value", ["240328", "250328", None])
def test_full_printed_date_survives_matching_conflicting_or_unreadable_mrz(name, mrz_value):
    printed = FieldValue(field_name=name, value="2024-03-28", value_kind="printed",
                         normalized_value="2024-03-28", observed_value="28 MAR 2024",
                         display_value="28-March-2024", source="visual", status="uncertain",
                         confidence=0.7, validation={"calendar_date": True})
    mrz = FieldValue(field_name=name, value=mrz_value, value_kind="mrz",
                     source="mrz", status="uncertain", confidence=0.99,
                     selection_basis="checked_mrz")
    for first, second in ((printed, mrz), (mrz, printed)):
        selected = merge_field(first, second)
        assert selected.value == selected.normalized_value == "2024-03-28"
        assert selected.display_value == "28-March-2024"
        assert selected.value_kind == "printed"


def test_mrz_is_a_fallback_when_print_is_unreadable():
    mrz = reading("A12345678", "mrz", "validated")
    for printed in (None, reading(None, status="uncertain")):
        selected = merge_field(printed, mrz)
        assert selected.value == mrz.value
        assert selected.value_kind == "mrz"


def partial_printed_date(text="??/??/1987", name="date_of_birth"):
    return FieldValue(
        field_name=name, value=text, observed_value=text, value_kind="printed",
        source="visual", confidence=0.95, status="uncertain",
        evidence=[Evidence(source="visual", raw_text=text, associated_label="Date of Birth")],
    )


def checked_mrz_date(text="870617", name="date_of_birth"):
    return FieldValue(
        field_name=name, value=text, observed_value=text, value_kind="mrz",
        source="mrz", confidence=0.95, status="uncertain", selection_basis="checked_mrz",
        validation={"mrz_field_check_digit": True},
        evidence=[Evidence(source="mrz", raw_text=text)],
    )


@pytest.mark.parametrize("name", ["date_of_birth", "date_of_expiry"])
def test_mrz_fallback_uses_only_matching_explicit_printed_year(name):
    printed, mrz = partial_printed_date(name=name), checked_mrz_date(name=name)
    for first, second in ((printed, mrz), (mrz, printed)):
        result = merge_field(first, second)
        assert result.normalized_value == "1987-06-17"
        assert result.display_value == "17-June-1987"
        assert result.observed_value == "870617"
        assert result.value_kind == "mrz"
        assert result.source == "multiple"
        assert result.status == "uncertain"
        assert result.validation["printed_year_agreement"] is True
        assert {item.source for item in result.evidence} == {"visual", "mrz"}


@pytest.mark.parametrize("text,mrz_text", [
    ("??/??/87", "870617"), ("??/??/1988", "870617"),
    ("??/??/1987 2087", "870617"), ("??/??/1900", "000229"),
    ("?? MAY 1987", "870617"), ("12/??/1987", "870617"),
])
def test_mrz_date_does_not_guess_or_rewrite_printed_year(text, mrz_text):
    result = merge_field(partial_printed_date(text), checked_mrz_date(mrz_text))
    assert result.normalized_value is None


def test_disagreeing_year_rereads_do_not_resolve_mrz_century():
    printed = partial_printed_date()
    printed.evidence.append(Evidence(source="visual", raw_text="??/??/2087"))
    result = merge_field(printed, checked_mrz_date())
    assert result.normalized_value is None


def test_unchecked_mrz_cannot_complete_a_partial_printed_date():
    mrz = checked_mrz_date().model_copy(update={"validation": {"mrz_field_check_digit": False}})
    result = merge_field(partial_printed_date(), mrz)
    assert result.normalized_value is None
