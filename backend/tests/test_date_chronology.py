"""Chronological checks preserve extracted labels and values; no OCR calls."""

import pytest

from app.extractors.field_extractor import _check_dates
from app.schemas.models import FieldValue


def dates(birth=None, issue=None, expiry=None):
    return {
        name: FieldValue(
            field_name=name, value=value, normalized_value=value,
            observed_value=value, status="detected", value_kind="printed",
        )
        for name, value in zip(
            ("date_of_birth", "date_of_issue", "date_of_expiry"),
            (birth, issue, expiry),
            strict=True,
        )
        if value is not None
    }


def test_reversed_dates_are_flagged_without_reassigning_any_value():
    fields = dates("2024-06-20", "2020-06-20", "2010-06-20")
    originals = {key: (field.value, field.normalized_value, field.observed_value)
                 for key, field in fields.items()}
    warnings = []
    _check_dates(fields, warnings)
    assert len(warnings) >= 3
    for key, field in fields.items():
        assert field.status == "uncertain"
        assert field.validation["chronological_order"] is False
        assert (field.value, field.normalized_value, field.observed_value) == originals[key]
        assert "dates have not been reassigned" in field.reason


def test_birth_and_expiry_are_compared_without_an_issue_date():
    fields = dates("2024-06-20", expiry="2020-06-20")
    _check_dates(fields, [])
    for field in fields.values():
        assert field.validation["birth_on_or_before_expiry"] is False
        assert field.validation["chronological_order"] is False


@pytest.mark.parametrize("birth,issue,expiry,ordered", [
    ("2020-01-01", "2020-02-01", "2020-03-01", True),
    ("2020-02-02", "2020-02-01", "2020-03-01", False),
    ("2020-01-01", "2020-03-02", "2020-03-01", False),
    ("2020-01-01", "2020-01-01", "2020-03-01", True),
])
def test_full_calendar_dates_are_compared_even_in_the_same_year(birth, issue, expiry, ordered):
    fields = dates(birth, issue, expiry)
    _check_dates(fields, [])
    assert all(field.validation["chronological_order"] is True for field in fields.values()) is ordered


@pytest.mark.parametrize("overrides", [
    {"value": "940423", "normalized_value": None, "value_kind": "mrz", "status": "uncertain"},
    {"value": "03/04/2000", "normalized_value": None, "validation": {"date_order_ambiguous": True}, "status": "uncertain"},
    {"status": "conflicting"},
    {"value": "2020-02-31", "normalized_value": "2020-02-31", "validation": {"calendar_date": False}, "status": "uncertain"},
])
def test_unknown_or_unresolved_dates_do_not_establish_order(overrides):
    fields = dates("2020-01-01", expiry="2010-01-01")
    fields["date_of_birth"] = fields["date_of_birth"].model_copy(update=overrides)
    original = fields["date_of_birth"].model_dump()
    _check_dates(fields, [])
    assert fields["date_of_birth"].validation["birth_on_or_before_expiry"] is None
    assert fields["date_of_birth"].status == original["status"]
    assert fields["date_of_birth"].value == original["value"]
    assert fields["date_of_expiry"].status == "detected"


def test_missing_date_does_not_claim_the_whole_chronology_is_verified():
    fields = dates("2000-01-01", expiry="2020-01-01")
    _check_dates(fields, [])
    assert fields["date_of_birth"].validation["birth_on_or_before_expiry"] is True
    assert fields["date_of_birth"].validation["chronological_order"] is None
