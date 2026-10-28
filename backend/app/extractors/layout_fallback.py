"""Conservative recovery for a recognizable Indian passport biodata layout.

This is a candidate association, never document validation. It requires a country
anchor, a partial passport MRZ, a printed given-name match, and aligned date/sex
rows. It never completes missing characters or invents a hidden passport number.
"""

import re
from datetime import date

from app.extractors.label_matcher import is_caption
from app.extractors.spatial_matcher import bounds
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


def indian_passport_candidates(
    lines: list[OCRLine], date_order: DateOrder
) -> tuple[dict[str, FieldValue], list[FieldValue]]:
    anchors = []
    for row in lines:
        text = re.sub(r"\s", "", row.text.upper())
        match = re.fullmatch(r"P<IND([A-Z]+(?:<[A-Z]+)*)<<([A-Z<]{3,45})", text)
        if match and row.confidence >= 0.65:
            anchors.append((row, match))
    if len(anchors) != 1:
        return {}, []
    mrz, match = anchors[0]
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
            row.text.strip().upper() == "IND"
            or "REPUBLICOFINDIA" in re.sub(r"[^A-Z]", "", row.text.upper())
        )
    ]
    if not country:
        return {}, []
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
        return FieldValue(
            field_name=name,
            value=value,
            status="uncertain",
            confidence=row.confidence,
            source="layout",
            bounding_box=row.bounding_box,
            reason="Possible reading from the Indian passport layout; labels are unclear. "
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
    fields["issuing_country"] = candidate("issuing_country", "IND", country[0])
    fields["sex"] = candidate("sex", sex.text.strip().upper(), sex)
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
        if name == "place_of_issue":
            other.append(field)
        else:
            fields[name] = field
    return fields, other
