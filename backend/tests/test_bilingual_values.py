from app.patterns.common import normalize_sex, paired_country_code
from app.schemas.models import FieldValue
from app.services.output import prepare_output


def test_local_initial_paired_with_standard_sex_marking():
    assert normalize_sex("K/M") == "M"
    assert normalize_sex("Q/F") == "F"


def test_two_different_sex_markings_stay_unresolved():
    assert normalize_sex("F/M") is None
    assert normalize_sex("KISI/M") is None


def test_country_pair_resolves_through_its_recognized_part():
    assert paired_country_code("AZORBAYCAN/AZERBAIJAN") == "AZE"
    assert paired_country_code("INDIA/AZERBAIJAN") is None
    assert paired_country_code("NOWHERE/ELSEWHERE") is None


def test_previous_passport_number_is_never_reported():
    field = FieldValue(field_name="previous_passport_number", value="A1234567", source="visual")
    result = prepare_output({"fields": {"previous_passport_number": field},
                             "other_fields": [field.model_copy()], "mrz": type("M", (), {"checksum_valid": None})()})
    assert "previous_passport_number" not in result["fields"]
    assert result["other_fields"] == []
