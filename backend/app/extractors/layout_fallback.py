"""Conservative recovery for a single-column passport biodata layout.

This is a candidate association, never document validation. It requires a printed
country anchor that agrees with the issuer slot of a partial passport MRZ, and
aligned text/date/sex rows. The issuing state is read from the document itself. Names are handled
by labeled OCR or independent MRZ fallback, never by comparing their spellings.
"""

import re
from datetime import date

from app.extractors.label_matcher import is_caption
from app.extractors.spatial_matcher import bounds
from app.patterns.common import icao_code_name
from app.patterns.dates import DateOrder, normalize_date
from app.schemas.models import Evidence, FieldValue, OCRLine


def _evidence(line: OCRLine, source: str = "visual") -> list[Evidence]:
    if line.observations:
        return [
            Evidence(
                source=source,
                raw_text=o.text,
                confidence=o.confidence,
                side=line.side,
                bounding_box=line.bounding_box,
                recognition_method=o.method,
            )
            for o in line.observations
        ]
    return [
        Evidence(
            source=source,
            raw_text=line.text,
            confidence=line.confidence,
            side=line.side,
            bounding_box=line.bounding_box,
        )
    ]


def _center_y(line: OCRLine) -> float:
    _, top, _, bottom = bounds(line)
    return (top + bottom) / 2


_DIGIT_LOOKALIKES = str.maketrans({"1": "I", "0": "O", "5": "S", "2": "Z", "8": "B"})


def _letters(text: str) -> str:
    return re.sub(r"[^A-Z]", "", text.upper())


def _country_names(code: str) -> set[str]:
    """Reference names for an ICAO issuer code, from the local country database."""
    import pycountry

    names = {icao_code_name(code) or ""}
    country = pycountry.countries.get(alpha_3="DEU" if code == "D" else code)
    if country:
        names.update(
            getattr(country, key, "") or "" for key in ("name", "official_name", "common_name")
        )
    return {_letters(name) for name in names if len(_letters(name)) >= 4}


def _printed_issuers(rows: list[OCRLine]) -> set[str]:
    """ICAO codes printed alone on a confident row, e.g. the country-code box."""
    return {
        code for row in rows
        if row.confidence >= 0.8
        and re.fullmatch(r"[A-Z]{1,3}", code := row.text.strip().upper())
        and icao_code_name(code)
    }


def passport_layout_candidates(
    lines: list[OCRLine], date_order: DateOrder
) -> tuple[dict[str, FieldValue], list[FieldValue]]:
    printed_issuers = _printed_issuers(lines)
    anchors = []
    for row in lines:
        text = re.sub(r"\s", "", row.text.upper())
        if len(text) < 10 or not text.startswith("P<") or row.confidence < 0.65:
            continue
        slot = text[2:5].translate(_DIGIT_LOOKALIKES)
        issuer = slot.rstrip("<")
        if not icao_code_name(issuer):
            # A damaged issuer slot is repaired only from a code printed on the
            # same document that differs from it by a single character.
            near = [code for code in printed_issuers if len(code) == len(slot)
                    and sum(a != b for a, b in zip(code, slot, strict=True)) == 1]
            if len(near) != 1:
                continue
            issuer = near[0]
        norm = "P<" + issuer.ljust(3, "<") + text[5:].translate(_DIGIT_LOOKALIKES)
        norm = re.sub(r"<[CK]", "<<", norm)
        match = re.fullmatch(r"P<[A-Z<]{3}([A-Z]+(?:<[A-Z]+)*)<<([A-Z<]{3,45})", norm)
        if match:
            anchors.append((row, match, issuer))
    if len(anchors) != 1:
        return {}, []
    mrz, match, issuer = anchors[0]
    issuer_names = _country_names(issuer)
    left, top, right, _ = bounds(mrz)
    width = right - left
    if width <= 0:
        return {}, []
    same_side = [row for row in lines if row.side == mrz.side and _center_y(row) < top]
    country = [
        row
        for row in same_side
        if row.confidence >= 0.8
        and (
            row.text.strip().upper() == issuer
            or any(name in _letters(row.text) for name in issuer_names)
        )
    ]
    if not country:
        return {}, []
    # Prefer the printed code itself to the broader document heading. This
    # preserves a direct visual observation when MRZ issuer rereads disagree.
    country.sort(key=lambda row: row.text.strip().upper() != issuer)
    column = [
        row
        for row in same_side
        if left + 0.25 * width <= bounds(row)[0] <= left + 0.5 * width and not is_caption(row.text)
    ]
    sexes = [
        row
        for row in same_side
        if row.text.strip().upper() in {"M", "F", "X"}
        and row.confidence >= 0.8
        and left + 0.5 * width <= bounds(row)[0] <= left + 0.85 * width
    ]
    if len(sexes) != 1:
        return {}, []
    sex = sexes[0]
    date_rows = [
        row
        for row in column
        if sum(c.isdigit() for c in row.text) >= 6
        and abs(_center_y(row) - _center_y(sex)) <= 0.045 * width
    ]
    if len(date_rows) != 1:
        return {}, []
    dob = date_rows[0]
    estimated_step = (top - _center_y(dob)) / 5.2
    given = [
        row
        for row in column
        if re.fullmatch(r"[A-Za-z][A-Za-z '-]{2,}", row.text)
        and abs(_center_y(row) - (_center_y(dob) - estimated_step)) < estimated_step * 0.45
    ]
    if len(given) != 1:
        return {}, []
    given_row = given[0]
    step = _center_y(dob) - _center_y(given_row)
    if not 0.025 * width <= step <= 0.10 * width:
        return {}, []
    # A single narrow data column and its MRZ must have plausible vertical spacing.
    if not 3.5 * step <= top - _center_y(dob) <= 7.5 * step:
        return {}, []
    fields: dict[str, FieldValue] = {}
    other: list[FieldValue] = []

    def candidate(name: str, value: str | None, row: OCRLine, reason: str = "") -> FieldValue:
        readings = [(row.text.strip(), row.confidence)] + [
            (item.text.strip(), item.confidence) for item in row.observations
        ]
        selected_scores = [score for text, score in readings if text == value]
        validation = {}
        if name.startswith("date_"):
            validation["calendar_date"] = (value is not None)
        return FieldValue(
            field_name=name,
            value=value,
            observed_value=value if selected_scores else (row.text.strip() if value is not None else None),
            display_value=value,
            value_kind=("printed" if selected_scores else "mrz") if value is not None else "unresolved",
            status="uncertain",
            confidence=min(selected_scores) if selected_scores else row.confidence,
            source="layout",
            bounding_box=row.bounding_box,
            validation=validation,
            reason="Possible reading from the passport biodata layout; labels are unclear. "
            + reason,
            evidence=_evidence(row) + _evidence(mrz, "mrz"),
        )

    observed_names = [(given_row.text.strip(), given_row.confidence)] + [
        (o.text.strip(), o.confidence) for o in given_row.observations
    ]
    corroborated = [
        text
        for text, score in observed_names
        if score >= 0.65
        and re.fullmatch(r"[A-Za-z][A-Za-z '-]{2,}", text)
        and match[2].startswith(re.sub(r"[ '-]", "<", text.upper()))
    ]
    fields["given_names"] = candidate(
        "given_names",
        corroborated[0] if corroborated else None,
        given_row,
        "The printed given names agree with the partial MRZ."
        if corroborated
        else "The printed name and partial MRZ do not agree; no spelling was selected.",
    )
    surname = match[1].replace("<", " ").strip()
    surname_rows = [
        row for row in column if abs(_center_y(row) - (_center_y(dob) - 2 * step)) <= step * 0.4
    ]
    if len(surname_rows) == 1:
        row = surname_rows[0]
        agreed = row.text.strip().upper() == surname and row.confidence >= 0.65
        fields["surname"] = candidate(
            "surname",
            row.text.strip() if agreed else None,
            row,
            "Printed surname agrees with the partial MRZ, which has no name check digit."
            if agreed
            else "The printed surname and partial MRZ do not agree; no spelling was selected.",
        )

    fields["issuing_country"] = candidate("issuing_country", issuer, country[0])
    fields["issuing_country"].normalized_value = issuer
    fields["issuing_country"].normalization_basis = (
        "Issuing-state code from the partial MRZ, corroborated by the document heading."
    )
    fields["country_code"] = fields["issuing_country"].model_copy(
        deep=True, update={"field_name": "country_code"},
    )
    fields["sex"] = candidate("sex", sex.text.strip(), sex)
    for name, offset in [
        ("date_of_birth", 0),
        ("place_of_birth", 1),
        ("place_of_issue", 2),
        ("date_of_issue", 3),
        ("date_of_expiry", 4),
    ]:
        target_y = _center_y(dob) + offset * step
        rows = [row for row in column if abs(_center_y(row) - target_y) <= step * 0.4]
        if len(rows) != 1:
            continue
        row = rows[0]
        value: str | None = row.text.strip()
        reason = ""
        if name.startswith("date_"):
            value, reason = normalize_date(value, date_order)
            if reason is None and not 1900 <= int(value[:4]) <= date.today().year + 30:
                reason = "The year is outside the supported passport date range."
            if reason:
                value = None
                reason = "Date unreadable; the raw reading is retained in source details. " + reason
        elif not re.fullmatch(r"[A-Za-z][A-Za-z ,.\-']{2,}", value):
            continue
        field = candidate(name, value, row, reason or "")
        # Row position proposes a candidate, but cannot establish which date
        # or locality was printed when the heading is unreadable. Keep the
        # observation for review instead of presenting a template guess.
        for item in field.evidence:
            if item.source == "visual":
                item.candidate_value = value or row.text.strip()
        field.value = field.observed_value = field.display_value = None
        field.value_kind = "unresolved"
        field.validation["heading_unresolved"] = True
        field.reason = "The printed heading is unreadable; layout-only candidates remain in evidence."
        if name == "place_of_issue":
            other.append(field)
        else:
            fields[name] = field
    return fields, other
