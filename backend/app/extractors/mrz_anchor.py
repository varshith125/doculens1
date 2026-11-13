"""Locate printed values by their agreement with independently checked MRZ fields.

When captions are unreadable a value cannot be assigned by its heading. A
printed line that equals an MRZ field whose own check digit is valid is still
identified by two independent readings. Nothing is repaired or invented: the
value shown is the printed text.
"""

import re
from dataclasses import dataclass

from app.extractors.mrz_parser import MRZ_ALPHABET, _check
from app.patterns.common import icao_code_name
from app.patterns.dates import DateOrder, normalize_date, valid_mrz_date
from app.schemas.models import OCRLine


@dataclass(frozen=True)
class NumericRow:
    # A stray character inside the number can leave several numbers that satisfy
    # its single check digit; the printed number decides between them.
    document_numbers: tuple[str, ...]
    nationality: str | None
    date_of_birth: str
    sex: str | None
    date_of_expiry: str


@dataclass(frozen=True)
class Anchor:
    field: str
    line: OCRLine
    value: str
    checked: bool  # Confirmed by an MRZ check digit, not only by matching text.


def aligned_numeric_row(row: str) -> NumericRow | None:
    """TD3 line-2 fields confirmed by three independent check digits.

    OCR can insert one stray character, which shifts every later field. The
    row is tried as read and with each single character removed. An alignment
    counts only when all three check digits pass, and every passing alignment
    must give the same nationality, dates and sex.
    """
    text = row.strip().upper().replace(" ", "")
    if not 40 <= len(text) <= 46 or not MRZ_ALPHABET.fullmatch(text):
        return None
    found: dict[tuple[str, str, str, str], list[str]] = {}
    for removed in (None, *range(28)):
        if removed is not None and removed == 0 and found:
            break  # The row passes exactly as read; no realignment is considered.
        variant = text if removed is None else text[:removed] + text[removed + 1:]
        number, dob, expiry = variant[:9], variant[13:19], variant[21:27]
        if (number.rstrip("<") and _check(number, variant[9])
                and _check(dob, variant[19]) and valid_mrz_date(dob)
                and _check(expiry, variant[27]) and valid_mrz_date(expiry)):
            numbers = found.setdefault((variant[10:13], dob, variant[20], expiry), [])
            if number.rstrip("<") not in numbers:
                numbers.append(number.rstrip("<"))
    if len(found) != 1:
        return None
    (nationality, dob, sex, expiry), numbers = next(iter(found.items()))
    known = re.fullmatch(r"[A-Z]{3}", nationality) and icao_code_name(nationality, nationality=True)
    return NumericRow(tuple(numbers), nationality if known else None, dob,
                      sex if sex in {"M", "F"} else None, expiry)


def _plain(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


def _printed_date(text: str, yymmdd: str, date_order: DateOrder) -> str | None:
    """ISO date of a printed four-digit-year date equal to an MRZ YYMMDD field."""
    for order in (("dmy", "mdy") if date_order == "auto" else (date_order,)):
        normalized, reason = normalize_date(text, order)
        if reason is None and normalized.replace("-", "")[2:] == yymmdd:
            return normalized
    return None


def _name_anchors(first_row: str, lines: list[OCRLine]) -> tuple[list[Anchor], str | None]:
    """Printed name lines found in order in the MRZ name row, and its issuer code.

    The surname is the printed name that directly follows a known three-letter
    issuing-state code near the start of the row. The row's first characters
    themselves may be misread or dropped, so they are not required.
    """
    text = _plain(first_row)
    if len(text) < 20 or "<" not in text:
        return [], None
    names = [(line, " ".join(line.text.upper().split())) for line in lines
             if line.confidence >= .90 and re.fullmatch(r"[A-Za-z]{2,}(?: [A-Za-z]+)*", line.text.strip())]
    surnames = []
    for line, value in names:
        start = text.find(value.replace(" ", "<"))
        issuer = text[start - 3:start] if start >= 3 else ""
        if 3 <= start <= 6 and re.fullmatch(r"[A-Z]{3}", issuer) and icao_code_name(issuer):
            surnames.append((line, value, start, issuer))
    if not surnames:
        return [], None
    line, surname, start, issuer = max(surnames, key=lambda item: len(item[1]))
    area = text[start:]
    anchors = [Anchor("surname", line, " ".join(line.text.split()), False)]
    # The separator may be misread; the given names still start right after it.
    given = [(row, value) for row, value in names if row is not line
             and 1 <= area.find(value.replace(" ", "<"), len(surname)) - len(surname) <= 3]
    if given:
        row, value = max(given, key=lambda item: len(item[1]))
        end = area.find(value.replace(" ", "<"), len(surname)) + len(value)
        if area[end:end + 1] in {"", "<"}:
            anchors.append(Anchor("given_names", row, " ".join(row.text.split()), False))
    return anchors, issuer


def anchor_printed_values(rows: list[str], lines: list[OCRLine], date_order: DateOrder) -> list[Anchor]:
    """Printed lines identified by a two-row passport MRZ. Empty when it cannot be aligned."""
    if len(rows) != 2:
        return []
    numeric = aligned_numeric_row(rows[1])
    if numeric is None:
        return []
    anchors, issuer = _name_anchors(rows[0], lines)
    used = {id(anchor.line) for anchor in anchors}

    def first(match) -> tuple[OCRLine, str] | None:
        for line in lines:
            if id(line) in used or line.confidence < .80:
                continue
            value = match(line.text)
            if value:
                used.add(id(line))
                return line, value
        return None

    numbers = [line for line in lines if id(line) not in used and line.confidence >= .80
               and _plain(line.text) in numeric.document_numbers]
    if len({_plain(line.text) for line in numbers}) == 1:
        used.add(id(numbers[0]))
        anchors.append(Anchor("document_number", numbers[0], numbers[0].text.strip(), True))
    for field, yymmdd in (("date_of_birth", numeric.date_of_birth), ("date_of_expiry", numeric.date_of_expiry)):
        found = first(lambda text, code=yymmdd: _printed_date(text, code, date_order))
        if found:
            anchors.append(Anchor(field, found[0], found[1], True))
    if numeric.sex:
        marks = [line for line in lines if id(line) not in used and line.text.strip().upper() in {"M", "F"}]
        if len(marks) == 1 and marks[0].text.strip().upper() == numeric.sex and marks[0].confidence >= .80:
            anchors.append(Anchor("sex", marks[0], numeric.sex, False))
    if issuer is None and re.match(r"P[A-Z<][A-Z]{3}", _plain(rows[0])):
        issuer = _plain(rows[0])[2:5]
    if issuer and re.fullmatch(r"[A-Z]{3}", issuer) and icao_code_name(issuer):
        code = first(lambda text: issuer if _plain(text) == issuer else None)
        if code:
            anchors.append(Anchor("country_code", code[0], issuer, False))
    # Elimination: with birth and expiry identified, one remaining complete date
    # between them can only be the date of issue.
    dates = {anchor.field: anchor.value for anchor in anchors if anchor.field.startswith("date_of_")}
    if len(dates) == 2:
        others = []
        for line in lines:
            if id(line) in used or line.confidence < .80:
                continue
            for order in (("dmy", "mdy") if date_order == "auto" else (date_order,)):
                normalized, reason = normalize_date(line.text, order)
                if reason is None and dates["date_of_birth"] < normalized < dates["date_of_expiry"]:
                    others.append((line, normalized))
                    break
        if len(others) == 1:
            anchors.append(Anchor("date_of_issue", others[0][0], others[0][1], False))
    if numeric.nationality:
        anchors.append(Anchor("nationality", OCRLine(
            text=rows[1], confidence=1.0, bounding_box=[[0, 0], [1, 0], [1, 1], [0, 1]],
            side=lines[0].side if lines else "front"), numeric.nationality, True))
    return anchors
