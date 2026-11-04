import re
import unicodedata
from datetime import date
from typing import Any

from app.extractors.caption_context import prepare_captions
from app.extractors.document_context import DocumentContext, classify_document, document_context
from app.extractors.label_matcher import match_label, match_labels
from app.extractors.layout_fallback import indian_passport_candidates
from app.extractors.mrz_parser import damaged_name_text, detect_mrz
from app.extractors.regions import contact_regions
from app.extractors.spatial_matcher import (
    SpatialScores,
    bounds,
    competing_labels,
    name_continuations,
    spatial_candidates,
)
from app.patterns.common import country_code, fold_text, icao_code_name, known_country_code
from app.patterns.dates import (
    DateOrder,
    date_context_warning,
    display_full_date,
    matches_mrz_date,
    normalize_date,
    normalize_mrz_date_century,
    valid_mrz_date,
)
from app.patterns.emirates_id import EMIRATES_ID_PATTERN, normalize_emirates_id
from app.patterns.passports import passport_number_matches
from app.schemas.models import CaptionFragment, Evidence, FieldValue, MRZResult, OCRLine

DATE_FIELDS = {"date_of_birth", "date_of_issue", "date_of_expiry"}
NAME_FIELDS = {"surname", "given_names", "first_name", "middle_names", "full_name"}
CHECKED_MRZ_FIELDS = {"document_number", "date_of_birth", "date_of_expiry"}
MIN_CONFIDENCE = 0.80


def _evidence(
    line: OCRLine,
    source: str = "visual",
    label: OCRLine | None = None,
    candidate_value: str | None = None,
    field_name: str | None = None,
) -> list[Evidence]:
    if line.observations:
        return [
            Evidence(
                source=source,
                raw_text=item.text,
                side=line.side,
                confidence=item.confidence,
                bounding_box=item.bounding_box or line.bounding_box,
                recognition_method=item.method,
                associated_label=label.text if label else None,
                label_bounding_box=label.bounding_box if label else None,
                candidate_value=candidate_value,
            )
            for item in line.observations
            if item.field_name is None or item.field_name == field_name
        ]
    return [
        Evidence(
            source=source,
            raw_text=line.text,
            side=line.side,
            confidence=line.confidence,
            bounding_box=line.bounding_box,
            associated_label=label.text if label else None,
            label_bounding_box=label.bounding_box if label else None,
            candidate_value=candidate_value,
        )
    ]


def _visual_value(
    name: str,
    value: str,
    line: OCRLine,
    label: OCRLine | None = None,
    date_order: DateOrder = "auto",
) -> FieldValue | None:
    value = value.strip()
    if not value or value in {"-", "—", "N/A", "NA"} or match_label(value):
        return None
    reason = None
    observed = value
    normalized = None
    normalization_basis = None
    validation: dict[str, bool | None] = {}
    semantic_name = name.removeprefix("emergency_contact_")
    if semantic_name in DATE_FIELDS:
        if not any(char.isdigit() for char in value):
            return None
        value, reason = normalize_date(value, date_order)
        issue_century_applied = False
        if reason is not None and semantic_name == "date_of_issue":
            value, reason = normalize_date(observed, date_order, expand_issue_year=True)
            issue_century_applied = reason is None
        if reason is None:
            normalized = value
            normalization_basis = f"Printed calendar date; numeric order setting: {date_order}."
            if issue_century_applied:
                normalization_basis += " Issue year uses the fixed century rule: 00-26 means 2000-2026; 27-99 means 1927-1999."
                validation["issue_century_rule_applied"] = True
        validation["calendar_date"] = (
            True if reason is None else False if "not a valid calendar" in reason else None
        )
        validation["date_order_ambiguous"] = bool(reason and "order is ambiguous" in reason)
        if reason is None and semantic_name in {"date_of_birth", "date_of_issue"}:
            reason = date_context_warning(value, semantic_name)
            validation["date_not_in_future"] = reason is None
            # A future date is a validation warning, not a reason to erase a
            # complete printed calendar date (including fictional documents).
        if issue_century_applied:
            reason = " ".join(filter(None, [reason,
                "The issue-date century was assigned using the fixed 26-year cutoff; review the original reading."]))
    elif semantic_name in NAME_FIELDS:
        if (
            not any(char.isalpha() for char in value)
            or damaged_name_text(value)
            or re.search(r"^[+•|]|[+•|]$", value)
        ):
            return None
        if any(char.isdigit() for char in value):
            reason = "The name reading contains digits; verify the printed spelling. No character substitutions were made."
    elif semantic_name == "document_code":
        if not re.fullmatch(r"[A-Za-z]{1,2}", value):
            return None
    elif semantic_name == "authority_code":
        if len(value) > 32 or not any(c.isalnum() for c in value) or not all(
            c.isalnum() or c in " ._/-" for c in value
        ):
            return None
    elif name.endswith("_number") and name != "emirates_id_number":
        # An unfamiliar observed format is retained for review, never replaced.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ./-]{0,39}", value) or not any(
            c.isdigit() for c in value
        ):
            reason = "Unfamiliar printed number format; verify the associated value."
    elif name == "emirates_id_number":
        normalized = normalize_emirates_id(value)
        if normalized:
            value = normalized
            normalization_basis = "Printed Emirates ID with formatting separators removed."
        else:
            reason = "The printed ID number does not match the 15-digit 784 pattern."
        validation["emirates_id_format"] = normalized is not None
    elif semantic_name in {"nationality", "issuing_country", "country_code"}:
        if semantic_name == "country_code" and not re.fullmatch(r"[A-Za-z]{3}|[Dd](?:<<)?", value):
            return None
        normalized = known_country_code(value)
        if not normalized and icao_code_name(value, nationality=semantic_name == "nationality"):
            normalized = value.upper().rstrip("<")
        if normalized:
            normalization_basis = "Supported country alias from this printed field only."
        else:
            reason = "Unrecognized nationality or issuing-state wording; verify the label association. The printed wording is preserved."
    elif semantic_name == "sex":
        sexes = {
            "m": "M", "male": "M", "masculin": "M", "man": "M", "mannelijk": "M",
            "f": "F", "female": "F", "feminin": "F", "vrouw": "F", "vrouwelijk": "F",
            "x": "X", "ذكر": "M", "انثى": "F",
        }
        tokens = [part.strip() for part in fold_text(value).split("/")]
        # V is Dutch female. Require the Dutch heading or its explicit V/F pair,
        # never infer this interpretation from nationality or a person's name.
        if (label and "geslacht" in fold_text(label.text)) or set(tokens) == {"v", "f"}:
            sexes["v"] = "F"
        readings = [sexes.get(token) for token in tokens]
        if all(readings) and len(set(readings)) == 1:
            normalized = value = readings[0]
            normalization_basis = "Supported printed sex marking; paired translations must agree."
        else:
            reason = "The printed sex marking is unrecognized or its translated readings disagree."
    confidence = min(line.confidence, label.confidence) if label else line.confidence
    review = line.review_required or (label is not None and label.review_required)
    validation["ocr_review_required"] = review
    # A noisy translated heading need not make a clearly read name unreadable.
    validation["value_ocr_review_required"] = line.review_required
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
        observed_value=observed,
        display_value=(
            display_full_date(normalized) if semantic_name in DATE_FIELDS and normalized
            else normalized if semantic_name == "sex" and normalized else observed
        ),
        normalized_value=normalized,
        normalization_basis=normalization_basis,
        value_kind="printed",
        validation=validation,
        status="uncertain" if reason else "detected",
        confidence=confidence,
        source="visual",
        bounding_box=line.bounding_box,
        reason=reason or "Selected the value associated with its printed heading.",
        evidence=[
            item.model_copy(update={"normalized_value": normalized, "validation": validation})
            for item in _evidence(line, label=label, candidate_value=observed)
        ],
    )


def _same_value(name: str, first: str, second: str) -> bool:
    if name in DATE_FIELDS:
        return first == second or matches_mrz_date(first, second) or matches_mrz_date(second, first)
    if name in {"issuing_country", "country_code", "nationality"}:
        first_code, second_code = country_code(first), country_code(second)
        if first_code and second_code:
            return first_code == second_code
    if name in {"document_number", "national_id_number", "personal_number", "emirates_id_number"}:
        # Formatting is preserved for display; comparison never substitutes characters.
        return re.sub(r"[\s-]", "", first).upper() == re.sub(r"[\s-]", "", second).upper()
    # Do not collapse letters or digits that OCR may have confused (O/0, I/1).
    return fold_text(first) == fold_text(second)


def _name_representations(value: str) -> set[str]:
    # MRZ may omit punctuation or encode it as fillers. Existing word boundaries
    # still matter: ANN ABEL and ANNA BEL must not become an apparent agreement.
    # Selected Latin transliterations from ICAO Doc 9303-3, section 6.A.
    # Expand only characters actually printed with these marks, before folding
    # accents. Plain MULLER must not become an apparent match for MUELLER.
    # https://www.icao.int/sites/default/files/publications/DocSeries/9303_p3_cons_en.pdf
    text = unicodedata.normalize("NFC", value).upper()
    latin = text.translate(str.maketrans({
        "Æ": "AE", "Œ": "OE", "Ø": "OE", "Ł": "L", "Þ": "TH",
        "Ð": "D", "Đ": "D", "Ħ": "H", "Ŋ": "N", "Ŧ": "T",
    }))
    expanded = latin.translate(str.maketrans({"Ä": "AE", "Å": "AA", "Ö": "OE", "Ü": "UE"}))
    return {
        " ".join(re.sub(r"[.'’ʼ‐‑–—-]", replacement, fold_text(spelling)).split())
        for spelling in (text, latin, expanded)
        for replacement in ("", " ")
    }


def _selection_basis(field: FieldValue) -> str:
    # A readable, associated printed value remains primary even when OCR asks
    # for review. A partial/ambiguous date is not an established printed date.
    if (
        field.value_kind == "printed"
        and field.value
        and (
            field.field_name not in DATE_FIELDS
            or (field.normalized_value and field.validation.get("calendar_date") is True
                and not field.validation.get("date_order_ambiguous"))
        )
    ):
        return "labeled_print"
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


def _selection_rank(field: FieldValue) -> int:
    priority = {"labeled_print": 4, "checked_mrz": 3, "ocr_reading": 1}
    return priority[_selection_basis(field)]


def _unresolved(field: FieldValue, evidence: list[Evidence], reason: str) -> FieldValue:
    return field.model_copy(
        update={
            "value": None,
            "display_value": None,
            "observed_value": None,
            "normalized_value": None,
            "normalization_basis": None,
            "value_kind": "unresolved",
            "selection_basis": None,
            "status": "conflicting",
            "source": "multiple",
            "confidence": None,
            "bounding_box": None,
            "validation": {},
            "evidence": evidence,
            "reason": reason,
        }
    )


def _mrz_date_with_printed_year(printed: FieldValue, mrz: FieldValue) -> FieldValue | None:
    """Use a labeled printed year, never an age/current-year century heuristic."""
    if not (
        printed.field_name == mrz.field_name
        and printed.field_name in {"date_of_birth", "date_of_expiry"}
        and printed.value_kind == "printed"
        and printed.status != "conflicting"
        and printed.normalized_value is None
        and printed.observed_value
        and (printed.confidence or 0) >= MIN_CONFIDENCE
        and printed.validation.get("calendar_date") is not False
        and not printed.validation.get("date_order_ambiguous")
        and not printed.validation.get("ocr_review_required")
        and not printed.validation.get("approximate_label_match")
        and any(item.source == "visual" and item.associated_label for item in printed.evidence)
        and mrz.value_kind == "mrz"
        and mrz.status != "conflicting"
        and mrz.value
        and valid_mrz_date(mrz.value)
        and _selection_basis(mrz) == "checked_mrz"
        and mrz.validation.get("mrz_field_check_digit") is True
    ):
        return None
    years = re.findall(r"(?<!\d)\d{4}(?!\d)", printed.observed_value)
    if len(years) != 1 or years[0][-2:] != mrz.value[:2]:
        return None
    remainder = re.sub(r"(?<!\d)\d{4}(?!\d)", "", printed.observed_value)
    if not re.fullmatch(r"[\s?_/\.\-–—]*", remainder):
        # Readable day/month fragments may conflict with the MRZ. Do not erase
        # them just because a four-digit year can be extracted from the text.
        return None
    alternative_years = {
        year for item in printed.evidence if item.source == "visual"
        for year in re.findall(r"(?<!\d)\d{4}(?!\d)", item.raw_text)
    }
    if alternative_years - {years[0]}:
        return None
    try:
        normalized = date(int(years[0]), int(mrz.value[2:4]), int(mrz.value[4:6])).isoformat()
    except ValueError:
        return None
    evidence = printed.evidence + [item for item in mrz.evidence if item not in printed.evidence]
    return mrz.model_copy(update={
        "value": normalized,
        "normalized_value": normalized,
        "display_value": display_full_date(normalized),
        "display_label": printed.display_label or mrz.display_label,
        "source": "multiple",
        "status": "uncertain",
        "confidence": min(printed.confidence or 0, mrz.confidence or 0),
        "selection_basis": "checked_mrz",
        "normalization_basis": "Day and month from checked MRZ; full year from the same labeled printed date with matching final year digits.",
        "reason": "MRZ fallback supplies the day and month of a partially readable printed date. The four-digit year is printed evidence, not an inferred century. Review both readings.",
        "validation": {
            **mrz.validation, "calendar_date": True,
            "printed_year_agreement": True, "source_agreement": None,
        },
        "evidence": evidence,
    })


def merge_field(existing: FieldValue | None, candidate: FieldValue) -> FieldValue:
    if existing is None:
        return candidate
    if existing.field_name in DATE_FIELDS:
        # A checked MRZ can resolve numeric order only when both full-year
        # interpretations come from the same observed print. It supplies no century.
        pair = [existing, candidate]
        for index, printed in enumerate(pair):
            mrz = pair[1 - index]
            if (
                printed.value_kind == "printed"
                and printed.status != "conflicting"
                and printed.validation.get("date_order_ambiguous")
                and printed.observed_value
                and mrz.value_kind == "mrz"
                and mrz.status != "conflicting"
                and _selection_basis(mrz) == "checked_mrz"
                and mrz.value
            ):
                matches = {
                    value for order in ("dmy", "mdy")
                    for value, reason in [normalize_date(printed.observed_value, order)]
                    if reason is None and matches_mrz_date(value, mrz.value)
                }
                if len(matches) == 1:
                    normalized = next(iter(matches))
                    pair[index] = printed.model_copy(update={
                        "value": normalized,
                        "normalized_value": normalized,
                        "display_value": display_full_date(normalized),
                        "normalization_basis": "Printed four-digit year retained; checked MRZ resolves day/month order. OCR remains subject to review.",
                        "validation": {**printed.validation, "calendar_date": True, "date_order_ambiguous": False},
                    })
        existing, candidate = pair
        for printed, mrz in ((existing, candidate), (candidate, existing)):
            recovered_date = _mrz_date_with_printed_year(printed, mrz)
            if recovered_date is not None:
                return recovered_date
    evidence = existing.evidence + [
        item for item in candidate.evidence if item not in existing.evidence
    ]
    cross_source = {existing.value_kind, candidate.value_kind} == {"printed", "mrz"}
    previous_agreements = [
        field.validation["source_agreement"] for field in (existing, candidate)
        if field.validation.get("source_agreement") is not None
    ]
    agreement_validation = (
        {"source_agreement": all(previous_agreements)} if previous_agreements else {}
    )
    if existing.status == "conflicting" and existing.value is None:
        return existing.model_copy(update={"evidence": evidence})
    if candidate.status == "conflicting" and candidate.value is None:
        return candidate.model_copy(update={"evidence": evidence})
    if existing.value is None or candidate.value is None:
        best = candidate if existing.value is None else existing
        note = (
            "Using MRZ as a fallback because the printed field has no selected value; printed evidence is retained."
            if best.value_kind == "mrz" and best.value else
            "Another association was unreadable; its evidence is retained."
        )
        return best.model_copy(update={
            "evidence": evidence,
            "display_label": existing.display_label or candidate.display_label,
            "reason": " ".join(filter(None, [best.reason, note])),
        })
    agrees = _same_value(existing.field_name, existing.value, candidate.value)
    name_representation_agrees = (
        existing.field_name in NAME_FIELDS
        and {existing.value_kind, candidate.value_kind} == {"printed", "mrz"}
        # Compare MRZ-compatible representations only across the two sources.
        # Preserve all spelling, accents and punctuation in the printed value.
        and bool(_name_representations(existing.value) & _name_representations(candidate.value))
    )
    if not agrees and not name_representation_agrees:
        if cross_source:
            agreement_validation = {"source_agreement": False}
        elif previous_agreements and all(previous_agreements):
            # Conflicting same-source values invalidate a previous agreement
            # claim until the alternative can be compared independently.
            agreement_validation = {"source_agreement": None}
        if (
            existing.value_kind == candidate.value_kind == "printed"
            or _selection_rank(existing) == _selection_rank(candidate)
        ):
            unresolved = _unresolved(
                existing, evidence,
                "Different printed values or equally supported sources remain. OCR confidence cannot resolve their association; no value was selected.",
            )
            # Same-source duplicates cannot establish printed/MRZ agreement.
            unresolved.validation = agreement_validation
            return unresolved
        best = max((existing, candidate), key=_selection_rank)
        basis = _selection_basis(best)
        explanation = {
            "labeled_print": "Keeping the associated printed reading as the primary value. The different MRZ reading is retained for cross-checking, not used to overwrite the print.",
            "checked_mrz": "Using checked MRZ as a fallback because no readable, established printed value was selected. The printed evidence remains available; checksums do not validate names, establish a date century or prove authenticity.",
            "ocr_reading": "Conflicting readings require verification against the original.",
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
                "reason": " ".join(filter(None, [best.reason, explanation[basis]])),
                "validation": {
                    **existing.validation, **candidate.validation, **best.validation,
                    **agreement_validation,
                },
            }
        )
    # Agreement is not permission to replace printed wording with a code or MRZ spelling.
    printed = [field for field in (existing, candidate) if field.value_kind == "printed"]
    best = printed[0] if printed else max((existing, candidate), key=_selection_rank)
    updates: dict[str, Any] = {
        "evidence": evidence,
        "display_label": existing.display_label or candidate.display_label,
        "source": "multiple" if existing.source != candidate.source else best.source,
        "selection_basis": _selection_basis(best),
        "validation": {
            **existing.validation, **candidate.validation, **best.validation,
            **({"source_agreement": True} if cross_source else {}), **agreement_validation,
        },
    }
    if name_representation_agrees and not agrees:
        updates["reason"] = "The printed name is compatible with the MRZ's spacing, punctuation and accent restrictions. The printed spelling is retained unchanged; both readings remain in evidence."
    if existing.field_name in DATE_FIELDS:
        visual = next(
            (
                field
                for field in (existing, candidate)
                if field.value_kind == "printed" and field.normalized_value is not None
            ),
            None,
        )
        mrz = next((field for field in (existing, candidate) if field.source == "mrz"), None)
        if visual and mrz:
            best = visual
            updates["status"] = "detected" if visual.status == "detected" else "uncertain"
            updates["reason"] = (
                "Printed full-year date agrees with the MRZ. A checksum does not independently validate its century."
            )
    if any(field.status == "conflicting" for field in (existing, candidate)):
        updates["status"] = "conflicting"
        updates["reason"] = " ".join(dict.fromkeys(filter(None, [
            existing.reason, candidate.reason,
            "This reading agrees with one candidate, but an earlier conflict remains unresolved.",
        ])))
    return best.model_copy(update=updates)


def _extract_visual(
    lines: list[OCRLine], date_order: DateOrder = "auto",
    contexts: dict[str, DocumentContext] | None = None,
) -> tuple[dict[str, FieldValue], dict[str, FieldValue]]:
    fields: dict[str, FieldValue] = {}
    other_fields: dict[str, FieldValue] = {}
    # Screenshots can include another application's JSON output below the image.
    # Preserve it in raw OCR, but do not use quoted object members as document labels.
    lines = [row for row in lines if not re.match(r'^\s*(?:\{|\[\s*\{|"[^"\n]+"\s*:)', row.text)]
    lines, caption_sources = prepare_captions(lines)
    spatial_scores: SpatialScores = {}
    contacts = contact_regions(lines)
    region_rows: dict[int | None, list[OCRLine]] = {}
    labels_by_row = {id(row): match_labels(row.text) for row in lines}
    for row in lines:
        region_rows.setdefault(contacts.get(id(row)), []).append(row)
    contexts = contexts if contexts is not None else document_context(lines)
    emirates_sides = {side for side, context in contexts.items() if context.kind == "emirates_id"}
    for line in lines:
        labels = labels_by_row[id(line)]
        caption_parts = caption_sources.get(id(line), [])
        printed_caption = " ".join(part.text for part in caption_parts)
        region = contacts.get(id(line))
        region_lines = region_rows[region]
        for label in labels:
            field_name = label.field_name
            if field_name == "national_id_number" and line.side in emirates_sides:
                # The label's meaning does not change when one digit is unreadable.
                field_name = "emirates_id_number"
            if region is not None:
                # A contact's names and numbers never compete with holder fields.
                field_name = "emergency_contact_" + field_name
            target = other_fields if label.additional or region is not None else fields
            values = (
                [(line, label.value)]
                if label.value
                and not (
                    label.field_name in DATE_FIELDS
                    and not any(char.isdigit() for char in label.value)
                )
                else [(item, item.text) for item in spatial_candidates(line, region_lines, spatial_scores)]
            )
            if len(labels) > 1 and not label.value:
                # One OCR box containing several headings has no per-heading
                # coordinates. Do not assign the same nearby row to each column.
                values = []
            if label.field_name in NAME_FIELDS | {"issuing_authority"}:
                # Start at the upper baseline even when the lower row is closer to its caption.
                values.sort(key=lambda item: (bounds(item[0])[1], bounds(item[0])[0]))
            consumed: set[int] = set()
            rejected: list[Evidence] = []
            accepted = False
            for value_line, value in values:
                if id(value_line) in consumed:
                    continue
                rivals = (
                    competing_labels(line, value_line, region_lines, scores=spatial_scores)
                    if value_line is not line else []
                )
                if rivals:
                    rejected.extend(_evidence(value_line, label=line, candidate_value=value))
                    rejected.extend(item for rival in rivals for item in _evidence(rival))
                    continue
                name = field_name
                candidate = _visual_value(name, value, value_line, line, date_order)
                if candidate and label.field_name in NAME_FIELDS | {"issuing_authority"} and len(labels) == 1:
                    fragments = name_continuations(line, value_line, region_lines, spatial_scores)
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
                            name, combined, joined, line, date_order
                        )
                        if candidate:
                            candidate.evidence = [
                                item for fragment in fragments
                                for item in _evidence(fragment, label=line, candidate_value=fragment.text)
                            ]
                if candidate:
                    accepted = True
                    if label.approximate:
                        candidate.status = "uncertain"
                        candidate.validation["approximate_label_match"] = True
                        candidate.reason = (candidate.reason or "") + " The field caption contains OCR errors; its wording and nearby value require review. The value itself was not corrected."
                    candidate.display_label = label.display_label
                    if caption_parts:
                        candidate.display_label = printed_caption
                        candidate.reason = (candidate.reason or "") + " Caption association uses the preserved OCR fragments."
                        for item in candidate.evidence:
                            item.associated_label = printed_caption
                            item.label_fragments = [CaptionFragment(
                                raw_text=part.text, bounding_box=part.bounding_box,
                            ) for part in caption_parts]
                    if region is not None:
                        candidate.display_label = "Emergency contact · " + (printed_caption or label.display_label or label.field_name.replace("_", " "))
                    target[name] = merge_field(target.get(name), candidate)
                else:
                    rejected.extend(_evidence(value_line, label=line, candidate_value=value))
            selected = target.get(field_name)
            if caption_parts:
                for item in rejected:
                    if item.associated_label == line.text:
                        item.associated_label = printed_caption
                        item.label_fragments = [CaptionFragment(
                            raw_text=part.text, bounding_box=part.bounding_box,
                        ) for part in caption_parts]
            if selected and rejected:
                selected.evidence.extend(item for item in rejected if item not in selected.evidence)
            if not accepted and field_name not in target:
                target[field_name] = FieldValue(
                    field_name=field_name,
                    display_label=("Emergency contact · " + (printed_caption or label.display_label or label.field_name)) if region is not None else (printed_caption or label.display_label),
                    status="uncertain",
                    value_kind="unresolved",
                    source="visual",
                    reason="The heading was detected, but no value could be associated unambiguously.",
                    evidence=[item for part in (caption_parts or [line]) for item in _evidence(part)] + rejected,
                )
        # Unknown colon-separated text stays in the original OCR transcript.
        # Punctuation alone does not establish an identity-field heading.
        for match in EMIRATES_ID_PATTERN.finditer(line.text):
            if region is not None:
                continue
            if line.side not in emirates_sides or labels or match.group() != line.text.strip():
                continue
            # A separately labeled card/personal/passport number is not an
            # Emirates ID merely because its digits happen to match the pattern.
            if any(
                owner is not line
                and any(label.field_name not in {"national_id_number", "emirates_id_number"}
                        for label in labels_by_row[id(owner)])
                and any(item is line for item in spatial_candidates(owner, region_lines, spatial_scores))
                for owner in region_lines
            ):
                continue
            observed = match.group()
            number = normalize_emirates_id(observed)
            candidate = FieldValue(
                field_name="emirates_id_number",
                value=number,
                observed_value=observed,
                display_value=observed,
                normalized_value=number,
                normalization_basis="Emirates ID pattern on the side with UAE document context.",
                value_kind="printed",
                status="uncertain",
                confidence=line.confidence,
                source="pattern",
                bounding_box=line.bounding_box,
                reason="An unlabelled number matches the Emirates ID format on an ID card. Verify its role against the original; formatting alone does not establish its identity.",
                evidence=_evidence(line, "pattern", candidate_value=observed),
            )
            fields["emirates_id_number"] = merge_field(fields.get("emirates_id_number"), candidate)
    return fields, other_fields


def _mrz_values(mrz: MRZResult, lines: list[OCRLine]) -> dict[str, FieldValue]:
    if not lines:
        return {}
    fields = {}
    for name, value in mrz.fields.items():
        if mrz.format == "TD1":
            row_index = 2 if name in NAME_FIELDS else 0 if name in {
                "document_code", "issuing_country", "document_number", "optional_data_1",
            } else 1
        else:
            row_index = 0 if name in NAME_FIELDS or name in {"document_code", "issuing_country"} else 1
        field_lines = lines[row_index:row_index + 1] or lines
        evidence = [item for line in field_lines for item in _evidence(line, "mrz", field_name=name)]
        confidence = min(line.confidence for line in field_lines)
        recovered_name = name in {"surname", "given_names"} and mrz.checks.get(name + "_reread") is True
        if recovered_name and mrz.checks.get(name + "_crop_reading"):
            matching_crops = [obs for line in field_lines for obs in line.observations
                              if obs.field_name == name
                              and " ".join(obs.text.upper().strip(" <").split()) == value]
            if matching_crops:
                confidence = min(obs.confidence for obs in matching_crops)
        field_review = any(line.review_required for line in field_lines)
        structure_key = name + "_structure"
        field_structure = mrz.checks.get(structure_key)
        if name in {"issuing_country", "nationality"} and not icao_code_name(
            value, nationality=name == "nationality",
        ):
            field_structure = False
        # A bad name character does not invalidate fixed numeric-row positions.
        # Keep the rejected field's evidence, but never present its invalid text
        # as a selected name or issuer.
        if field_structure is None and mrz.checks.get("structure") is False:
            field_structure = name in CHECKED_MRZ_FIELDS or name.startswith("optional_data")
        is_date = name in DATE_FIELDS
        display = value if field_structure is not False and (not is_date or valid_mrz_date(value)) else None
        reason = None
        checked = bool(mrz.checksum_valid and field_structure is not False)
        status = "validated" if checked and name in CHECKED_MRZ_FIELDS else "detected"
        if not mrz.checksum_valid:
            status, reason = (
                "uncertain",
                "MRZ validation failed; verify against the printed document.",
            )
        elif name in DATE_FIELDS:
            status, reason = (
                "uncertain",
                "MRZ encodes YYMMDD without a century. The source reading is shown unchanged because a full date cannot be established. The century has not been inferred.",
            )
        elif name in {"surname", "given_names"}:
            reason = "MRZ names have no check digit and may use transliteration or truncation."
            if any("truncated" in warning for warning in mrz.warnings):
                status = "uncertain"
        if recovered_name:
            status = "uncertain"
            reason = (
                "This name component was recovered from corroborated MRZ OCR crops. "
                "Names have no checksum; verify the spelling against the image."
            )
            if mrz.checks.get(name + "_reading_conflict"):
                reason += " Other crop readings differ; their text is retained in Technical details."
        if confidence < MIN_CONFIDENCE:
            status = "uncertain"
            reason = (reason + " " if reason else "") + "OCR confidence is low."
        if mrz.corrections:
            status = "uncertain"
            reason = (reason or "") + " Position-constrained MRZ substitutions were applied; review raw and interpreted lines in Technical details."
        if field_review:
            status = "uncertain"
            reason = (
                reason + " " if reason else ""
            ) + "OCR rereads differed; review the preserved observations."
        if is_date and display is None:
            status = "uncertain"
            reason = (reason + " " if reason else "") + (
                "MRZ date is incomplete or invalid; no date was selected. The raw reading remains in source evidence."
            )
        if field_structure is False:
            status = "uncertain"
            reason = "This MRZ field has invalid or incomplete structure; no value was selected. Other independently positioned fields remain available."
        fields[name] = FieldValue(
            field_name=name,
            value=value if display is not None else None,
            status=status,
            confidence=confidence,
            source="mrz",
            observed_value=value if recovered_name else mrz.raw_fields.get(name, value),
            display_value=display,
            value_kind="mrz" if display is not None else "unresolved",
            normalized_value=value if display is not None and name in {"nationality", "issuing_country"} else None,
            normalization_basis=(
                "Code read at the MRZ field position; no country-name expansion."
                if display is not None and name in {"nationality", "issuing_country"} else None
            ),
            selection_basis=(
                "checked_mrz"
                if checked and display is not None and confidence >= MIN_CONFIDENCE
                and not field_review
                else "ocr_reading"
            ),
            validation={
                "ocr_review_required": field_review,
                "mrz_structure": mrz.checks.get("structure"),
                "mrz_field_structure": field_structure,
                "mrz_field_check_digit": mrz.checks.get(name),
                "mrz_composite": mrz.checks.get("composite"),
                "mrz_all_checks": mrz.checksum_valid,
                "mrz_name_recovered": recovered_name,
                **({"icao_country_code": mrz.checks.get(name + "_code_known")}
                   if name in {"issuing_country", "nationality"} else {}),
            },
            bounding_box=None,
            reason=reason,
            evidence=[
                item.model_copy(update={
                    "candidate_value": value,
                    "validation": {"field_check_digit": mrz.checks.get(name), "structure": mrz.checks.get("structure"), "composite": mrz.checks.get("composite")},
                })
                for item in evidence
            ],
        )
    return fields


def _readable_printed(field: FieldValue | None) -> bool:
    """Decide from OCR evidence alone whether a printed value can be used."""
    if (field is None or field.value_kind != "printed" or not field.value
            or field.status == "conflicting"
            or (field.confidence is not None and field.confidence < MIN_CONFIDENCE)
            or field.validation.get("value_ocr_review_required",
                                    field.validation.get("ocr_review_required"))):
        return False
    if field.field_name in NAME_FIELDS:
        return (not damaged_name_text(field.value)
                and not any(c.isdigit() for c in field.value)
                and not any(c in field.value for c in "?\ufffd"))
    return not any(c in field.value for c in "?\ufffd")


def _usable_mrz_value(candidate: FieldValue) -> bool:
    field_consensus = (
        _issuer_slot_agrees(candidate)
        or _document_code_slot_agrees(candidate)
        or _mrz_name_consensus(candidate)
        or (candidate.validation.get("mrz_name_recovered") is True
            and candidate.field_name in {"surname", "given_names"})
    )
    usable = (
        bool(candidate.value) and candidate.value_kind == "mrz"
        and (candidate.confidence is None or candidate.confidence >= MIN_CONFIDENCE or field_consensus)
        and candidate.validation.get("mrz_field_structure") is not False
        and (not candidate.validation.get("ocr_review_required") or field_consensus)
    )
    if candidate.field_name in NAME_FIELDS:
        usable = usable and not damaged_name_text(candidate.value or "")
    return usable


def _issuer_slot_agrees(candidate: FieldValue) -> bool:
    """Allow an uncertain issuer code only when repeated MRZ reads agree on its slot."""
    if (
        candidate.field_name not in {"issuing_country", "country_code"}
        or candidate.validation.get("mrz_field_structure") is not True
        or not candidate.validation.get("icao_country_code")
        or not candidate.value
    ):
        return False
    code = candidate.value.strip().upper().rstrip("<")
    rows = {
        re.sub(r"\s+", "", item.raw_text).upper()
        for item in candidate.evidence
        if item.source == "mrz" and item.raw_text and "<<" in item.raw_text
    }
    return len(rows) >= 2 and all(len(row) >= 5 and row[2:5] == code for row in rows)


def _document_code_slot_agrees(candidate: FieldValue) -> bool:
    """Trust a repeated passport code independently of damaged name/padding text."""
    if (candidate.field_name != "document_code"
            or candidate.validation.get("mrz_field_structure") is not True
            or not candidate.value or not re.fullmatch(r"P[A-Z]?", candidate.value)):
        return False
    readings = {
        (item.recognition_method, item.raw_text): re.sub(r"\s+", "", item.raw_text).upper()
        for item in candidate.evidence
        if item.source == "mrz" and item.raw_text
        and item.confidence is not None and item.confidence >= 0.65
        and len(re.sub(r"\s+", "", item.raw_text)) >= 25
        and "<" in item.raw_text
    }
    return len(readings) >= 2 and all(
        re.fullmatch(r"P[A-Z<]", text[:2]) and text[:2].rstrip("<") == candidate.value
        for text in readings.values()
    )


def _mrz_name_consensus(candidate: FieldValue) -> bool:
    """Require a majority of repeated MRZ reads to agree on a specific name field."""
    if candidate.field_name not in {"surname", "given_names"} or not candidate.value:
        return False
    expected = " ".join(candidate.value.upper().split())
    readings = []
    for item in candidate.evidence:
        if item.source != "mrz" or not item.raw_text:
            continue
        line = re.sub(r"\s+", "", item.raw_text).upper()
        if len(line) < 40 or "<<" not in line[5:]:
            continue
        surname, _, given = line[5:].partition("<<")
        segment = surname if candidate.field_name == "surname" else given
        segment = re.split(r"<{2,}", segment, maxsplit=1)[0]
        value = " ".join(segment.replace("<", " ").split())
        if value and re.fullmatch(r"[A-Z]+(?: [A-Z]+)*", value):
            readings.append(value)
    matches = sum(value == expected for value in readings)
    return len(readings) >= 2 and matches > len(readings) / 2


def _cross_validate_printed(
    printed: FieldValue, candidate: FieldValue, comparison_value: str | None = None,
    *, printed_comparison: str | None = None,
) -> FieldValue:
    """Report OCR/MRZ agreement while leaving readable printed OCR selected."""
    if not _usable_mrz_value(candidate):
        return printed
    compared = comparison_value if comparison_value is not None else candidate.value
    if not compared:
        return printed
    printed_value = printed_comparison if printed_comparison is not None else printed.value or ""
    agrees = _same_value(printed.field_name, printed_value, compared)
    if (not agrees and printed.field_name in NAME_FIELDS
            and _name_representations(printed_value) & _name_representations(compared)):
        agrees = True
    evidence = printed.evidence + [item for item in candidate.evidence if item not in printed.evidence]
    cross_check_note = (
        "The readable printed OCR value agrees with the MRZ. The printed wording remains selected."
        if agrees else
        "The readable printed OCR value differs from the MRZ. The printed wording remains selected; review both readings."
    )
    return printed.model_copy(update={
        "evidence": evidence,
        "validation": {**printed.validation, "source_agreement": agrees},
        "reason": " ".join(filter(None, [printed.reason, cross_check_note])),
    })


def _mrz_fallback(
    existing: FieldValue | None,
    candidate: FieldValue,
    *,
    comparison_value: str | None = None,
) -> FieldValue:
    """Keep readable print primary; cross-check it, or use MRZ as fallback."""
    if _readable_printed(existing):
        return _cross_validate_printed(existing, candidate, printed_comparison=comparison_value)
    if existing and existing.value_kind == "mrz":
        # Two separate MRZ records still need ambiguity handling.
        return merge_field(existing, candidate)
    usable = _usable_mrz_value(candidate)
    if not usable:
        if existing:
            if existing.field_name not in NAME_FIELDS or _readable_printed(existing):
                return existing
            return existing.model_copy(update={
                "value": None, "display_value": None, "normalized_value": None,
                "value_kind": "unresolved", "status": "uncertain",
                "reason": "The printed name is unreadable and no readable MRZ fallback is available.",
            })
        return candidate.model_copy(update={
            "value": None, "display_value": None, "normalized_value": None,
            "value_kind": "unresolved", "status": "uncertain",
            "reason": "The MRZ reading is not clear enough to supply this missing field.",
        })
    reason = "MRZ fallback: the printed field is missing or unreadable. " + (candidate.reason or "")
    if _document_code_slot_agrees(candidate):
        reason += " The document type code agrees across repeated readings of the MRZ prefix. This does not validate the remaining MRZ fields."
    if _issuer_slot_agrees(candidate) and candidate.validation.get("mrz_structure") is False:
        reason += " The issuer-code slot agrees across repeated OCR readings, but the overall MRZ structure failed; verify this value against the printed document."
    elif _mrz_name_consensus(candidate) and candidate.validation.get("mrz_structure") is False:
        reason += " This name component agrees across most MRZ OCR readings, but the overall MRZ structure failed; verify this value against the printed document."
    return candidate.model_copy(update={
        "display_label": existing.display_label if existing else candidate.display_label,
        "reason": reason,
        "validation": {**candidate.validation, "mrz_fallback": True,
                       **({"mrz_document_code_agreement": True} if _document_code_slot_agrees(candidate) else {})},
        "evidence": candidate.evidence + (existing.evidence if existing else []),
    })


def _apply_mrz_date_centuries(fields: dict[str, FieldValue]) -> None:
    """Expand selected MRZ birth/expiry dates after considering printed years."""
    old_note = (
        "MRZ encodes YYMMDD without a century. The source reading is shown unchanged "
        "because a full date cannot be established. The century has not been inferred."
    )
    for name, kind in (("date_of_birth", "birth"), ("date_of_expiry", "expiry")):
        field = fields.get(name)
        if (field is None or field.value_kind != "mrz" or not field.value
                or field.normalized_value is not None or field.status == "conflicting"):
            continue
        normalized = normalize_mrz_date_century(field.value)
        if normalized is None:
            continue
        basis = f"MRZ {kind} year uses the fixed century rule: 00-26 means 2000-2026; 27-99 means 1927-1999."
        field.reason = " ".join(filter(None, [
            (field.reason or "").replace(old_note, "").strip(), basis,
            "The century is assigned by this rule, not verified by the MRZ checksum.",
        ]))
        field.value = field.normalized_value = normalized
        field.display_value = display_full_date(normalized)
        field.normalization_basis = basis
        field.validation.update({"calendar_date": True, f"{kind}_century_rule_applied": True})
        field.status = "uncertain"


def _check_dates(fields: dict[str, FieldValue], warnings: list[str]) -> None:
    dates: dict[str, date] = {}
    for name in DATE_FIELDS:
        field = fields.get(name)
        # Only compare established full dates. An MRZ YYMMDD reading or an
        # ambiguous numeric reading cannot establish chronological order.
        value = (field.normalized_value or field.value) if field else None
        if (
            field
            and field.status not in {"conflicting", "not_detected"}
            and field.value_kind != "unresolved"
            and (field.value_kind != "mrz" or field.normalized_value is not None)
            and field.validation.get("calendar_date") is not False
            and not field.validation.get("date_order_ambiguous")
            and value
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
        ):
            try:
                dates[name] = date.fromisoformat(value)
            except ValueError:
                continue
    for name in ("date_of_birth", "date_of_issue"):
        if name not in dates:
            continue
        field = fields[name]
        message = date_context_warning(dates[name].isoformat(), name)
        field.validation["date_not_in_future"] = message is None
        if name == "date_of_issue":
            field.validation["issue_not_in_future"] = message is None
        if message:
            field.status = "uncertain"
            if message not in (field.reason or ""):
                field.reason = (field.reason or "") + " " + message
            if name == "date_of_birth":
                field.validation["birth_year_plausible"] = False
            warnings.append(message)
            # Compare the observed dates even when their chronology is unusual;
            # plausibility checks do not change the printed calendar values.
    if "date_of_birth" in dates and date.today().year - dates["date_of_birth"].year > 130:
        fields["date_of_birth"].status = "uncertain"
        fields["date_of_birth"].reason = (fields["date_of_birth"].reason or "") + " The observed birth year is unusually old; verify the printed year. It has not been rewritten."
        fields["date_of_birth"].validation["birth_year_plausible"] = False
    comparisons = (
        ("date_of_birth", "date_of_issue", "birth_on_or_before_issue"),
        ("date_of_issue", "date_of_expiry", "issue_on_or_before_expiry"),
        ("date_of_birth", "date_of_expiry", "birth_on_or_before_expiry"),
    )
    for name in DATE_FIELDS & fields.keys():
        fields[name].validation["chronological_order"] = True if len(dates) == 3 else None
    for earlier, later, check in comparisons:
        ordered = dates[earlier] <= dates[later] if earlier in dates and later in dates else None
        for name in (earlier, later):
            if name in fields:
                fields[name].validation[check] = ordered
        if ordered is False:
            message = f"{earlier.replace('_', ' ').capitalize()} is later than {later.replace('_', ' ')}."
            warnings.append(message)
            for name in (earlier, later):
                fields[name].status = "uncertain"
                fields[name].reason = " ".join(filter(None, [
                    fields[name].reason, message,
                    "Review the original document; dates have not been reassigned.",
                ]))
                fields[name].validation["chronological_order"] = False
    if "date_of_expiry" in dates and dates["date_of_expiry"] < date.today():
        warnings.append("The detected expiry date is in the past.")


def _cross_check_issuer(fields: dict[str, FieldValue]) -> None:
    country, code = fields.get("issuing_country"), fields.get("country_code")
    if not country or not code or not country.value or not code.value:
        return
    if country.value_kind != "printed" or code.value_kind != "printed":
        return
    country_value = known_country_code(country.value)
    code_value = known_country_code(code.value)
    if not country_value or not code_value:
        return
    agrees = country_value == code_value
    for field in (country, code):
        field.validation["issuing_country_code_agreement"] = agrees
        if not agrees:
            field.status = "conflicting"
            field.reason = (field.reason or "") + " Issuing country and country code disagree; both readings are retained for review."


def _assemble_full_name(fields: dict[str, FieldValue]) -> None:
    # A printed full name has its own order; do not reinterpret it as a surname.
    if "full_name" in fields:
        return
    given, surname = fields.get("given_names") or fields.get("first_name"), fields.get("surname")
    if not given or not surname or not given.value or not surname.value:
        return
    if given.value_kind == surname.value_kind == "mrz":
        sides = {item.side for part in (given, surname) for item in part.evidence if item.source == "mrz"}
        if len(sides) != 1 or given.status == "conflicting" or surname.status == "conflicting":
            return
        fields["full_name"] = FieldValue(
            field_name="full_name", display_label="Full Name (assembled)",
            value=f"{given.value} {surname.value}",
            display_value=f"{given.value} {surname.value}",
            value_kind="assembled", source="assembled", status="uncertain",
            confidence=min(given.confidence or 0, surname.confidence or 0),
            validation={"mrz_name_assembly": True},
            reason="Display name assembled as MRZ given names followed by surname. This order is a display convention, not a separately printed full name. Components and raw MRZ remain available; spelling may be incomplete.",
            evidence=given.evidence + [item for item in surname.evidence if item not in given.evidence],
        )
        return
    parts = [given]
    middle = fields.get("middle_names")
    if middle and not middle.value:
        return
    if middle and middle.value:
        parts.append(middle)
    parts.append(surname)
    # MRZ order is not a universal display order. Assemble only when printed
    # components establish an order on one side; otherwise leave them separate.
    if any(
        part.value_kind != "printed" or part.status != "detected" or not part.bounding_box
        for part in parts
    ):
        return
    sides = {item.side for part in parts for item in part.evidence if item.source == "visual"}
    if len(sides) != 1:
        return
    parts.sort(key=lambda part: min(point[1] for point in part.bounding_box or []))
    boxes = [bounds(part) for part in parts]
    for a, b in zip(boxes, boxes[1:], strict=False):
        height = max(1, a[3] - a[1], b[3] - b[1])
        if b[1] < a[3] or abs(a[0] - b[0]) > height * 1.5:
            return
    # Overlapping or repeated component readings do not establish distinct names.
    for index, part in enumerate(parts):
        tokens = fold_text(part.value or "").split()
        for other in parts[index + 1:]:
            other_tokens = fold_text(other.value or "").split()
            if any(other_tokens[start:start + len(tokens)] == tokens for start in range(len(other_tokens))) or any(
                tokens[start:start + len(other_tokens)] == other_tokens for start in range(len(tokens))
            ):
                return
    combined = " ".join(part.value for part in parts if part.value)
    fields["full_name"] = FieldValue(
        field_name="full_name",
        display_label="Full Name (assembled)",
        value=combined,
        display_value=combined,
        value_kind="assembled",
        status="detected",
        confidence=min(part.confidence or 0 for part in parts),
        source="assembled",
        reason="Assembled in the observed top-to-bottom order of a single printed column. This is not a separately printed full-name field; components remain unchanged.",
        evidence=[item for part in parts for item in part.evidence],
    )


def extract_fields(lines: list[OCRLine], date_order: DateOrder = "auto") -> dict[str, Any]:
    contexts = document_context(lines)
    fields, other = _extract_visual(lines, date_order, contexts)
    warnings: list[str] = []
    mrzs: list[MRZResult] = []
    printed_kinds = {context.kind for context in contexts.values() if context.kind != "unknown"}
    if "emirates_id" in printed_kinds:
        printed_kinds.discard("identity_card")
    printed_kind = next(iter(printed_kinds)) if len(printed_kinds) == 1 else "unknown"
    for side in ("front", "back"):
        mrz, evidence = detect_mrz([line for line in lines if line.side == side])
        if not mrz.detected:
            continue
        mrzs.append(mrz)
        warnings.extend(mrz.warnings)
        if printed_kind in {"emirates_id", "identity_card"} and mrz.format == "TD3":
            note = "A passport MRZ was found alongside identity-card headings. The MRZ is preserved separately and was not merged into the cardholder's printed fields."
            warnings.append(note)
            mrz.warnings.append(note)
            continue
        for name, candidate in _mrz_values(mrz, evidence).items():
            printed_number = fields.get("document_number")
            if (name == "document_number" and mrz.format in {"TD1", "TD2"}
                    and printed_number and printed_number.value_kind == "printed"
                    and re.search(r"\b(?:passport|passeport|pasaporte)\b",
                                  printed_number.display_label or "", re.IGNORECASE)):
                # A card can separately print the holder's passport number.
                # The card MRZ document-number slot is not that passport field.
                candidate = candidate.model_copy(update={"field_name": "mrz_document_number"})
                candidate.reason = (candidate.reason or "") + " The card MRZ document number is separate from the printed passport number."
                other["mrz_document_number"] = merge_field(other.get("mrz_document_number"), candidate)
                continue
            if name == "given_names" and "first_name" in fields and "given_names" not in fields:
                first = fields["first_name"]
                if _readable_printed(first):
                    # A first-name label corresponds to the first token of the
                    # MRZ given-name sequence. Keep the full sequence intact
                    # for its own field and compare only that first token here.
                    first_mrz_token = (candidate.value or "").split()
                    if first_mrz_token:
                        fields["first_name"] = _cross_validate_printed(
                            first, candidate, comparison_value=first_mrz_token[0],
                        )
                    continue
                # The MRZ has a given-name sequence, not a first/middle split.
                # A single token can fill an explicitly labeled first-name field.
                if candidate.value and len(candidate.value.split()) == 1 and "middle_names" not in fields:
                    name = "first_name"
                    candidate = candidate.model_copy(update={"field_name": name})
            if name == "issuing_country":
                # The same MRZ slot supports a code and its country-name lookup.
                # It supplies no issuing office, authority code or place of issue.
                code = candidate.model_copy(deep=True, update={"field_name": "country_code"})
                fields["country_code"] = _mrz_fallback(fields.get("country_code"), code)
            target = (
                other if name.startswith("optional_data") or name == "document_code" else fields
            )
            comparison_value = None
            if name == "given_names":
                given = fields.get("given_names")
                middle = fields.get("middle_names")
                if (given and given.value_kind == "printed" and given.value
                        and middle and middle.value_kind == "printed" and middle.value
                        and given.status != "conflicting" and middle.status != "conflicting"):
                    comparison_value = f"{given.value} {middle.value}"
            target[name] = _mrz_fallback(
                target.get(name), candidate, comparison_value=comparison_value,
            )
    mrz = mrzs[0] if mrzs else MRZResult()
    layout_recognized = False
    for side in ("front", "back"):
        if contexts[side].kind in {"emirates_id", "identity_card"} or printed_kind in {"emirates_id", "identity_card"}:
            # Passport-only layout recovery must not populate fields on an ID.
            continue
        recovered, additional = indian_passport_candidates(
            [row for row in lines if row.side == side], date_order
        )
        layout_recognized = layout_recognized or bool(recovered)
        for name, field in recovered.items():
            # Unlabeled layout names were selected by matching against MRZ.
            # Names now require a printed heading or their own MRZ fallback.
            if name not in fields and name not in NAME_FIELDS:
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
    document_type, document_type_reason = classify_document(contexts, mrzs, layout_recognized)
    if document_type == "passport":
        for name, target in (("issuing_authority", fields), ("authority_code", other)):
            if name not in target:
                target[name] = FieldValue(
                    field_name=name, value=None, value_kind="unresolved", status="uncertain",
                    source="visual",
                    reason="No identifiable printed label and value were found. The MRZ does not supply this field.",
                )
    if document_type == "unknown" and (
        any(context.ambiguous or context.kind != "unknown" for context in contexts.values())
        or len({item.format for item in mrzs if item.checksum_valid}) > 1
    ):
        warnings.append(document_type_reason)
    _cross_check_issuer(fields)
    country = fields.get("country_code") or fields.get("issuing_country")
    issuing_country = (
        country_code(country.value)
        if country and country.value and country.status not in {"uncertain", "conflicting"}
        else None
    )
    number = fields.get("document_number")
    if document_type == "passport" and number and number.value and issuing_country:
        comparison_number = re.sub(r"\s", "", number.value).upper()
        matches = passport_number_matches(comparison_number, issuing_country)
        number.validation["configured_passport_format"] = matches
        if matches is True and number.value_kind == "printed":
            number.normalized_value = comparison_number
            number.normalization_basis = "Printed passport number, uppercased without spacing for format comparison; no character substitutions."
        if matches is False:
            if number.status != "conflicting":
                number.status = "uncertain"
            number.reason = (
                (number.reason + " " if number.reason else "")
                + "Number does not match the configured current passport format for this issuing country; older or exceptional formats may differ."
            )
    for name in NAME_FIELDS & fields.keys():
        field = fields[name]
        if field.value_kind == "printed" and not _readable_printed(field):
            fields[name] = field.model_copy(update={
                "value": None, "display_value": None, "normalized_value": None,
                "value_kind": "unresolved", "status": "uncertain",
                "reason": "The printed name is unreadable and no readable MRZ fallback is available.",
            })
    _assemble_full_name(fields)
    _apply_mrz_date_centuries(fields)
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
        "document_type_reason": document_type_reason,
        "document_type_evidence": [item for context in contexts.values()
                                   for row in context.headings for item in _evidence(row)],
        "issuing_country": issuing_country,
        "fields": fields,
        "mrz": mrz,
        "other_fields": list(other.values()),
        "warnings": list(dict.fromkeys(warnings)),
    }
