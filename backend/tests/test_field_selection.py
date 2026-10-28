from app.extractors.field_extractor import merge_field
from app.schemas.models import Evidence, FieldValue


def reading(value, source="visual", status="detected", confidence=0.94):
    return FieldValue(
        field_name="document_number",
        value=value,
        source=source,
        status=status,
        confidence=confidence,
        evidence=[Evidence(source=source, raw_text=value or "Unreadable")],
    )


def test_clear_labeled_print_wins_over_higher_confidence_mrz_without_hiding_conflict():
    visual = reading("A12345678")
    mrz = reading("A12345670", "mrz", "validated", 0.999)
    for first, second in ((visual, mrz), (mrz, visual)):
        selected = merge_field(first, second)
        assert selected.value == visual.value
        assert selected.status == "conflicting"
        assert selected.selection_basis == "labeled_print"
        assert len(selected.evidence) == 2
        assert selected.model_dump()["selection_basis"] == "labeled_print"


def test_validated_mrz_can_resolve_uncertain_print_with_visible_mismatch():
    selected = merge_field(
        reading("A12345670", status="uncertain"),
        reading("A12345678", "mrz", "validated", 0.90),
    )
    assert selected.value == "A12345678"
    assert selected.status == "conflicting"
    assert selected.selection_basis == "checked_mrz"


def test_selection_provenance_survives_agreement_then_later_disagreement():
    selected = merge_field(reading("A12345678"), reading("A12345678", "mrz", "validated"))
    selected = merge_field(selected, reading("A12345670", "mrz", "validated", 1))
    assert selected.value == "A12345678"
    assert selected.selection_basis == "labeled_print"
    assert len(selected.evidence) == 3


def test_unreadable_candidate_evidence_is_retained():
    selected = merge_field(reading(None, status="uncertain"), reading("A12345678"))
    assert selected.value == "A12345678"
    assert len(selected.evidence) == 2
