"""PRD output normalization. Observations and conflicting evidence stay intact."""
import re

import pycountry

from app.patterns.common import icao_code_name, known_country_code
from app.patterns.dates import display_full_date
from app.patterns.emirates_id import normalize_emirates_id

NAME_LABELS = {
    "surname": "Surname", "given_names": "Given Names",
    "first_name": "First Name", "middle_names": "Middle Names",
    "full_name": "Full Name",
}


def _place_of_birth_display(value: str) -> str:
    """Repair punctuation between a recognized US state and country only."""
    states = pycountry.subdivisions.get(country_code="US") or []
    state_names = {
        re.sub(r"[^A-Z0-9]", "", item.name.upper()): item.name
        for item in states
    }
    aliases = {"USA", "US", "U.S.A.", "UNITED STATES", "UNITED STATES OF AMERICA"}
    country_keys = {re.sub(r"[^A-Z0-9]", "", name.upper()) for name in aliases}

    raw = " ".join(value.split()).strip()
    compact = re.sub(r"[^A-Z0-9]", "", raw.upper())
    for state_key, state_name in state_names.items():
        for country_key in country_keys:
            if compact == state_key + country_key:
                return f"{state_name}, USA"

    parts = [part.strip(" .;/|:") for part in re.split(r"[,;:/|]+|\.(?=\s|[A-Za-z])", raw)]
    parts = [part for part in parts if part]
    if len(parts) >= 2:
        country_key = re.sub(r"[^A-Z0-9]", "", parts[-1].upper())
        area_key = re.sub(r"[^A-Z0-9]", "", parts[-2].upper())
        if country_key in country_keys:
            area = state_names.get(area_key, parts[-2])
            return f"{area}, USA"
    return re.sub(r"\s*,\s*", ", ", raw)


def prepare_output(extracted: dict) -> dict:
    for field in [*extracted["fields"].values(), *extracted["other_fields"]]:
        if field.field_name in NAME_LABELS:
            field.display_label = NAME_LABELS[field.field_name]
            if field.value_kind == "assembled":
                field.display_label += " (assembled)"
        field.raw = field.observed_value
        if field.validation.get("date_order_ambiguous") and not field.normalized_value:
            field.value = field.display_value = None
        if not field.bounding_box:
            source = "mrz" if field.value_kind == "mrz" else "visual"
            field.bounding_box = next((item.bounding_box for item in field.evidence
                                       if item.source == source and item.bounding_box), None)
        if field.bounding_box:
            field.box = [min(p[0] for p in field.bounding_box), min(p[1] for p in field.bounding_box),
                         max(p[0] for p in field.bounding_box), max(p[1] for p in field.bounding_box)]
        if field.value is None:
            continue
        key = field.field_name
        if key in {"nationality", "issuing_country", "country_code"}:
            # Keep ICAO and ISO representations separate. In particular D<<
            # encodes Germany in the MRZ; replacing it with DEU loses that reading.
            code = (field.value.strip().upper().rstrip("<") if key == "country_code"
                    else known_country_code(field.value) or field.value.strip().upper())
            name = icao_code_name(code, nationality=key == "nationality")
            country = pycountry.countries.get(alpha_3="DEU" if code == "D" else code)
            field.validation["iso_country_code"] = country is not None
            field.validation["icao_country_code"] = name is not None
            if name:
                field.code = code
                field.code_source = field.source
                field.country_name = name
                if key == "issuing_country":
                    field.value = field.display_value = name
                    field.normalization_basis = "Country/state name resolved from this field's code or printed wording; original reading remains in raw and evidence."
                elif key == "country_code":
                    field.value = field.display_value = code
                else:
                    wording = field.value if field.value_kind == "printed" else name
                    field.display_value = f"{wording} ({code})"
            elif field.status != "conflicting":
                field.status = "uncertain"
        if key == "place_of_birth":
            formatted_place = _place_of_birth_display(field.value)
            if formatted_place != field.value:
                field.value = field.display_value = field.normalized_value = formatted_place
                field.normalization_basis = (
                    "Recognized US state and country boundary; punctuation and spacing standardized. "
                    "The original OCR reading remains in raw and evidence."
                )
                field.validation["place_punctuation_normalized"] = True
        if key == "emirates_id_number":
            digits = normalize_emirates_id(field.value)
            if digits:
                field.value = field.display_value = f"{digits[:3]}-{digits[3:7]}-{digits[7:14]}-{digits[14]}"
            # No authoritative checksum algorithm is specified in the PRD.
            field.validation["id_check_digit"] = None
        if key in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
            if field.normalized_value:
                field.value = field.normalized_value
                field.display_value = display_full_date(field.normalized_value)
            else:
                # Retain the selected reading without claiming a normalized date
                # or inventing an MRZ century. Unresolved associations stay empty.
                field.display_value = field.display_value or field.observed_value or field.value
                field.value = None
                if field.status != "conflicting":
                    field.status = "uncertain"
                field.reason = (field.reason or "") + " Full date unavailable; the source reading is retained without normalization."
    from app.extractors.field_extractor import _same_value
    for field in extracted["fields"].values():
        if field.field_name != "full_name" and "source_agreement" not in field.validation:
            visual_ev = [e for e in field.evidence if e.source == "visual"]
            mrz_ev = [e for e in field.evidence if e.source == "mrz"]
            if visual_ev and mrz_ev and field.value:
                mrz_val = mrz_ev[0].candidate_value or mrz_ev[0].raw_text or ""
                field.validation["source_agreement"] = _same_value(
                    field.field_name, field.value, mrz_val
                )
    agreements = [f.validation["source_agreement"] for f in extracted["fields"].values()
                  if f.validation.get("source_agreement") is not None
                  and any(item.source == "visual" for item in f.evidence)
                  and any(item.source == "mrz" for item in f.evidence)]
    extracted["checks"] = {
        "mrz_checksums_valid": extracted["mrz"].checksum_valid,
        "mrz_matches_printed": all(agreements) if agreements else None,
    }
    return extracted
