import re
from datetime import date
from typing import Any

from app.extractors.label_matcher import match_label, match_labels
from app.extractors.layout_fallback import indian_passport_candidates
from app.extractors.mrz_parser import detect_mrz
from app.extractors.spatial_matcher import bounds, name_continuations, spatial_candidates
from app.patterns.common import country_code, fold_text
from app.patterns.dates import DateOrder, matches_mrz_date, normalize_date, valid_mrz_date
from app.patterns.emirates_id import find_emirates_ids, normalize_emirates_id
from app.patterns.passports import passport_number_matches
from app.schemas.models import Evidence, FieldValue, MRZResult, OCRLine

DATE_FIELDS = {"date_of_birth", "date_of_issue", "date_of_expiry"}
NAME_FIELDS = {"surname", "given_names", "middle_names", "full_name"}
CHECKED_MRZ_FIELDS = {"document_number", "date_of_birth", "date_of_expiry"}
MIN_CONFIDENCE = 0.80


def _evidence(line: OCRLine, source: str = "visual") -> list[Evidence]:
    if line.observations:
        return [
            Evidence(
                source=source,
                raw_text=item.text,
                side=line.side,
                confidence=item.confidence,
                bounding_box=line.bounding_box,
                recognition_method=item.method,
            )
            for item in line.observations
        ]
    return [
        Evidence(
            source=source,
            raw_text=line.text,
            side=line.side,
            confidence=line.confidence,
            bounding_box=line.bounding_box,
        )
    ]


def _visual_value(
    name: str,
    value: str,
    line: OCRLine,
    label: OCRLine | None = None,
    date_order: DateOrder = "auto",
) -> FieldValue | None:
    value = " ".join(value.strip().split())
    if not value or value in {"-", "—", "N/A", "NA"} or match_label(value):
        return None
    reason = None
    if name in DATE_FIELDS:
        if not any(char.isdigit() for char in value):
            return None
        value, reason = normalize_date(value, date_order)
    elif name in NAME_FIELDS:
        if (
            not any(char.isalpha() for char in value)
            or any(char.isdigit() for char in value)
            or "<" in value
        ):
            return None
    elif name in {"document_number", "personal_number"}:
        value = re.sub(r"\s", "", value).upper()
        if not re.fullmatch(r"[A-Z0-9-]{5,24}", value) or not any(char.isdigit() for char in value):
            return None
    elif name == "emirates_id_number":
        normalized = normalize_emirates_id(value)
        if normalized:
            value = normalized
        else:
            reason = "The printed ID number does not match the 15-digit 784 pattern."
    elif name == "sex":
        sexes = {"m": "M", "male": "M", "f": "F", "female": "F", "x": "X", "ذكر": "M", "انثى": "F"}
        value = sexes.get(fold_text(value), value)
        if value not in {"M", "F", "X"}:
            reason = "The printed sex value is unrecognized."
    confidence = min(line.confidence, label.confidence) if label else line.confidence
    review = line.review_required or (label is not None and label.review_required)
    if review:
        reason = " ".join(
            filter(
                None,
                [
                    reason,
                    line.recognition_note or (label.recognition_note if label else None),
                    "Verify the reread against the original image.",
                ],
            )
        )
    if confidence < MIN_CONFIDENCE:
        reason = (
            "Low OCR confidence; inspect the printed value."
            if not reason
            else reason + " OCR confidence is also low."
        )
    return FieldValue(
        field_name=name,
        value=value,
        status="uncertain" if reason else "detected",
        confidence=confidence,
        source="visual",
        bounding_box=line.bounding_box,
        reason=reason,
        evidence=_evidence(line),
    )


def _same_value(name: str, first: str, second: str) -> bool:
    if name in DATE_FIELDS:
        return first == second or matches_mrz_date(first, second) or matches_mrz_date(second, first)
    if name in {"issuing_country", "nationality"}:
        first_code, second_code = country_code(first), country_code(second)
        if first_code and second_code:
            return first_code == second_code
    # Do not collapse letters or digits that OCR may have confused (O/0, I/1).
    return fold_text(first) == fold_text(second)


def _selection_basis(field: FieldValue) -> str:
    if field.selection_basis:
        return field.selection_basis
    if (
        field.source == "visual"
        and field.status == "detected"
        and (field.confidence or 0) >= MIN_CONFIDENCE
    ):
        return "labeled_print"
    if field.source == "mrz" and field.status == "validated":
        return "checked_mrz"
    return "ocr_reading"


def _selection_rank(field: FieldValue) -> tuple[int, float]:
    priority = {"labeled_print": 3, "checked_mrz": 2, "ocr_reading": 1}
    return priority[_selection_basis(field)], field.confidence or 0


def merge_field(existing: FieldValue | None, candidate: FieldValue) -> FieldValue:
    if existing is None:
        return candidate
    evidence = existing.evidence + [
        item for item in candidate.evidence if item not in existing.evidence
    ]
    if existing.value is None or candidate.value is None:
        best = candidate if existing.value is None else existing
        return best.model_copy(update={"evidence": evidence})
    if existing.status == "conflicting" or not _same_value(
        existing.field_name, existing.value, candidate.value
    ):
        best = max((existing, candidate), key=_selection_rank)
        basis = _selection_basis(best)
        explanation = {
            "labeled_print": "Showing the clearly labeled printed reading. A different reading remains available for verification.",
            "checked_mrz": "Showing the checksum-validated MRZ reading because the printed reading is uncertain. Verify the difference against the original.",
            "ocr_reading": "Showing the highest-confidence available reading. Other readings differ; verify against the original.",
        }
        return best.model_copy(
            update={
                "status": "conflicting",
                "source": "multiple",
                "display_label": best.display_label
                or existing.display_label
                or candidate.display_label,
                "selection_basis": basis,
                "evidence": evidence,
                "reason": explanation[basis],
            }
        )
    best = (
        candidate
        if candidate.status == "validated" and existing.status != "validated"
        else existing
    )
    updates: dict[str, Any] = {
        "evidence": evidence,
        "display_label": existing.display_label or candidate.display_label,
        "source": "multiple" if existing.source != candidate.source else best.source,
        "selection_basis": _selection_basis(max((existing, candidate), key=_selection_rank)),
    }
    if existing.field_name in DATE_FIELDS:
        visual = next(
            (
                field
                for field in (existing, candidate)
                if field.source == "visual" and normalize_date(field.value or "")[1] is None
            ),
            None,
        )
        mrz = next((field for field in (existing, candidate) if field.source == "mrz"), None)
        if visual and mrz:
            updates["value"] = visual.value
            updates["status"] = "detected" if visual.status == "detected" else "uncertain"
            updates["reason"] = (
                "Printed full-year date agrees with the MRZ. A checksum does not independently validate its century."
            )
    return best.model_copy(update=updates)


def _extract_visual(
    lines: list[OCRLine], date_order: DateOrder = "auto"
) -> tuple[dict[str, FieldValue], dict[str, FieldValue]]:
    fields: dict[str, FieldValue] = {}
    other_fields: dict[str, FieldValue] = {}
    for line in lines:
        labels = match_labels(line.text)
        for label in labels:
            target = other_fields if label.additional else fields
            values = (
                [(line, label.value)]
                if label.value
                and not (
                    label.field_name in DATE_FIELDS
                    and not any(char.isdigit() for char in label.value)
                )
                else [(item, item.text) for item in spatial_candidates(line, lines)]
            )
            if label.field_name in NAME_FIELDS:
                # Start at the upper baseline even when the lower row is closer to its caption.
                values.sort(key=lambda item: (bounds(item[0])[1], bounds(item[0])[0]))
            consumed: set[int] = set()
            for value_line, value in values:
                if id(value_line) in consumed:
                    continue
                candidate = _visual_value(label.field_name, value, value_line, line, date_order)
                if candidate and label.field_name in NAME_FIELDS and len(labels) == 1:
                    fragments = name_continuations(line, value_line, lines)
                    if len(fragments) > 1:
                        consumed.update(id(item) for item in fragments)
                        combined = " ".join([value, *[item.text for item in fragments[1:]]])
                        boxes = [bounds(item) for item in fragments]
                        x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
                        x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
                        joined = value_line.model_copy(
                            update={
                                "text": combined,
                                "confidence": min(item.confidence for item in fragments),
                                "bounding_box": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                                "review_required": any(item.review_required for item in fragments),
                            }
                        )
                        candidate = _visual_value(
                            label.field_name, combined, joined, line, date_order
                        )
                        if candidate:
                            candidate.evidence = [
                                item for fragment in fragments for item in _evidence(fragment)
                            ]
                if candidate:
                    candidate.display_label = label.display_label
                    target[label.field_name] = merge_field(target.get(label.field_name), candidate)
        if not labels and ":" in line.text:
            caption, value = line.text.split(":", 1)
            if (
                2 <= len(caption.strip()) <= 40
                and value.strip()
                and all(char.isalpha() or char.isspace() for char in caption)
            ):
                name = "_".join(fold_text(caption).split())
                candidate = _visual_value(name, value, line)
                if candidate:
                    other_fields[name] = merge_field(other_fields.get(name), candidate)
        for number in find_emirates_ids(line.text):
            candidate = FieldValue(
                field_name="emirates_id_number",
                value=number,
                status="detected"
                if line.confidence >= MIN_CONFIDENCE and not line.review_required
                else "uncertain",
                confidence=line.confidence,
                source="pattern",
                bounding_box=line.bounding_box,
                reason="Matches the Emirates ID number format; this is not an authenticity check.",
                evidence=_evidence(line, "pattern"),
            )
            fields["emirates_id_number"] = merge_field(fields.get("emirates_id_number"), candidate)
    return fields, other_fields


def _mrz_values(mrz: MRZResult, lines: list[OCRLine]) -> dict[str, FieldValue]:
    if not lines:
        return {}
    confidence = min(line.confidence for line in lines)
    evidence = [item for line in lines for item in _evidence(line, "mrz")]
    fields = {}
    for name, value in mrz.fields.items():
        reason = None
        checked = (
            name in CHECKED_MRZ_FIELDS and mrz.checks.get(name) and mrz.checks.get("composite")
        )
        status = "validated" if checked else "detected"
        if not mrz.checksum_valid:
            status, reason = (
                "uncertain",
                "MRZ validation failed; verify against the printed document.",
            )
        elif name in DATE_FIELDS:
            status, reason = (
                "uncertain",
                "MRZ encodes YYMMDD without a century. The six printed digits are preserved.",
            )
            if not valid_mrz_date(value):
                reason = (
                    "MRZ date is incomplete or invalid; no missing date components were inferred."
                )
        elif name in {"surname", "given_names"}:
            reason = "MRZ names have no check digit and may use transliteration or truncation."
            if any("truncated" in warning for warning in mrz.warnings):
                status = "uncertain"
        if confidence < MIN_CONFIDENCE:
            status = "uncertain"
            reason = (reason + " " if reason else "") + "OCR confidence is low."
        if any(line.review_required for line in lines):
            status = "uncertain"
            reason = (
                reason + " " if reason else ""
            ) + "OCR rereads differed; review the preserved observations."
        fields[name] = FieldValue(
            field_name=name,
            value=value,
            status=status,
            confidence=confidence,
            source="mrz",
            bounding_box=None,
            reason=reason,
            evidence=evidence,
        )
    return fields


def _check_dates(fields: dict[str, FieldValue], warnings: list[str]) -> None:
    dates = {}
    for name in DATE_FIELDS:
        field = fields.get(name)
        if (
            field
            and field.status != "conflicting"
            and field.value
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", field.value)
        ):
            try:
                dates[name] = date.fromisoformat(field.value)
            except ValueError:
                continue
    if "date_of_birth" in dates and dates["date_of_birth"] > date.today():
        fields["date_of_birth"].status = "uncertain"
        fields["date_of_birth"].reason = "The printed date of birth is in the future."
    for earlier, later in (("date_of_birth", "date_of_issue"), ("date_of_issue", "date_of_expiry")):
        if earlier in dates and later in dates and dates[earlier] > dates[later]:
            warnings.append(
                f"{earlier.replace('_', ' ').capitalize()} is later than {later.replace('_', ' ')}."
            )
            for name in (earlier, later):
                fields[name].status = "uncertain"
                fields[name].reason = "Printed dates have an inconsistent order."
    if "date_of_expiry" in dates and dates["date_of_expiry"] < date.today():
        warnings.append("The detected expiry date is in the past.")


def _assemble_full_name(fields: dict[str, FieldValue]) -> None:
    # A printed full name has its own order; do not reinterpret it as a surname.
    if "full_name" in fields:
        return
    given, surname = fields.get("given_names"), fields.get("surname")
    if not given or not surname or not given.value or not surname.value:
        return
    parts = [given]
    middle = fields.get("middle_names")
    if middle and middle.value:
        parts.append(middle)
    parts.append(surname)
    # Keep original components separately, including conflicts and their provenance.
    status = (
        "conflicting"
        if any(f.status == "conflicting" for f in parts)
        else ("uncertain" if any(f.status == "uncertain" for f in parts) else "detected")
    )
    fields["full_name"] = FieldValue(
        field_name="full_name",
        value=" ".join(part.value for part in parts if part.value),
        status=status,
        confidence=min(part.confidence or 0 for part in parts),
        source="assembled",
        reason="Combined the separate printed name components; the original given names, middle names and surname are unchanged.",
        evidence=[item for part in parts for item in part.evidence],
    )


def extract_fields(lines: list[OCRLine], date_order: DateOrder = "auto") -> dict[str, Any]:
    fields, other = _extract_visual(lines, date_order)
    warnings: list[str] = []
    mrzs: list[MRZResult] = []
    for side in ("front", "back"):
        mrz, evidence = detect_mrz([line for line in lines if line.side == side])
        if not mrz.detected:
            continue
        mrzs.append(mrz)
        warnings.extend(mrz.warnings)
        for name, candidate in _mrz_values(mrz, evidence).items():
            target = (
                other if name.startswith("optional_data") or name == "document_code" else fields
            )
            target[name] = merge_field(target.get(name), candidate)
    mrz = mrzs[0] if mrzs else MRZResult()
    layout_recognized = False
    for side in ("front", "back"):
        recovered, additional = indian_passport_candidates(
            [row for row in lines if row.side == side], date_order
        )
        layout_recognized = layout_recognized or bool(recovered)
        for name, field in recovered.items():
            if name not in fields:
                fields[name] = field
        for field in additional:
            if field.field_name not in other:
                other[field.field_name] = field
    if len(mrzs) > 1 and mrzs[0].fields != mrzs[1].fields:
        warnings.append(
            "The two sides contain different MRZ records. Review conflicting fields before use."
        )
        mrz = mrz.model_copy(
            update={
                "warnings": mrz.warnings
                + ["A different MRZ was found on the other side; see field evidence."],
                "checksum_valid": False,
            }
        )
    full_text = "\n".join(line.text for line in lines if line.confidence >= MIN_CONFIDENCE)
    passport_title = bool(
        re.search(r"\b(?:PASSPORT|PASSEPORT|PASAPORTE)\b", full_text, re.IGNORECASE)
    )
    id_title = bool(
        re.search(r"\b(?:IDENTITY CARD|EMIRATES ID|RESIDENT IDENTITY)\b", full_text, re.IGNORECASE)
    )
    if fields.get("emirates_id_number") and fields["emirates_id_number"].status == "detected":
        document_type = "emirates_id"
    elif (
        layout_recognized
        or passport_title
        or any(item.format == "TD3" and item.checksum_valid for item in mrzs)
    ):
        document_type = "passport"
    elif id_title or any(item.format in {"TD1", "TD2"} and item.checksum_valid for item in mrzs):
        document_type = "identity_card"
    else:
        document_type = "unknown"
    country = fields.get("issuing_country")
    issuing_country = (
        country_code(country.value)
        if country and country.value and country.status not in {"uncertain", "conflicting"}
        else None
    )
    number = fields.get("document_number")
    if document_type == "passport" and number and number.value and issuing_country:
        matches = passport_number_matches(number.value, issuing_country)
        if matches is False:
            if number.status != "conflicting":
                number.status = "uncertain"
            number.reason = (
                (number.reason + " " if number.reason else "")
                + "Number does not match the configured current passport format for this issuing country; older or exceptional formats may differ."
            )
    _assemble_full_name(fields)
    _check_dates(fields, warnings)
    if any(field.status == "conflicting" for field in fields.values()):
        warnings.append(
            "Some readings differ. Review the marked fields; alternatives and the reason for selection remain in the optional source details."
        )
    if not lines:
        warnings.append(
            "No readable text was detected. Use a sharper, well-lit image with the whole document visible."
        )
    elif not fields:
        warnings.append(
            "Text was read, but no identity fields could be associated reliably. Inspect the OCR transcript."
        )
    return {
        "document_type": document_type,
        "issuing_country": issuing_country,
        "fields": fields,
        "mrz": mrz,
        "other_fields": list(other.values()),
        "warnings": list(dict.fromkeys(warnings)),
    }
