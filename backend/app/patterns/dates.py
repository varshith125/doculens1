import re
import unicodedata
from datetime import date
from typing import Literal

DateOrder = Literal["auto", "dmy", "mdy"]

MONTHS = {
    "JAN": 1,
    "JANUARY": 1,
    "JANV": 1,
    "FEB": 2,
    "FEBRUARY": 2,
    "FEV": 2,
    "FEVR": 2,
    "MAR": 3,
    "MARCH": 3,
    "MARS": 3,
    "APR": 4,
    "APRIL": 4,
    "AVR": 4,
    "MAY": 5,
    "MAI": 5,
    "JUN": 6,
    "JUNE": 6,
    "JUIN": 6,
    "JUL": 7,
    "JULY": 7,
    "JUIL": 7,
    "AUG": 8,
    "AUGUST": 8,
    "AOUT": 8,
    "SEP": 9,
    "SEPT": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVEMBER": 11,
    "DEC": 12,
    "DECEMBER": 12,
}


def normalize_date(value: str, date_order: DateOrder = "auto") -> tuple[str, str | None]:
    """Use explicit date order or unambiguous calendar evidence; never infer a century."""
    from app.patterns.common import fold_text

    text = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in value)
    text = fold_text(text).upper().strip().replace(",", " ")
    text = re.sub(r"[‐‑–—]", "-", text)
    text = re.sub(r"\s*([-/.])\s*", r"\1", text)
    text = re.sub(r"(?<=[A-Z])\.(?=\s|/|$)", "", text)
    text = re.sub(r"\s+", " ", text)
    if date_order != "auto" and re.fullmatch(r"\d{8}", text):
        text = f"{text[:2]}/{text[2:4]}/{text[4:]}"
    iso = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    numeric = re.fullmatch(r"(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{4})", text)
    named = re.fullmatch(r"(\d{1,2})[-/. ]?([A-Z]+)(?:/([A-Z]+))?[-/. ]?(\d{4})", text)
    month_first = re.fullmatch(r"([A-Z]+)[-/. ](\d{1,2})[-/. ](\d{4})", text)
    parts: tuple[int, int, int] | None = None
    if iso:
        parts = tuple(map(int, iso.groups()))
    elif numeric:
        first, second, year = map(int, numeric.groups())
        if date_order == "dmy":
            parts = (year, second, first)
        elif date_order == "mdy":
            parts = (year, first, second)
        elif first <= 12 and second <= 12 and first != second:
            return value, "Day/month order is ambiguous; the printed value is preserved."
        else:
            parts = (
                (year, second, first) if first > 12 or first == second else (year, first, second)
            )
    elif named and named[2] in MONTHS:
        if named[3] and MONTHS.get(named[3]) != MONTHS[named[2]]:
            return value, "Printed month names disagree or are unsupported."
        parts = (int(named[4]), MONTHS[named[2]], int(named[1]))
    elif month_first and month_first[1] in MONTHS:
        parts = (int(month_first[3]), MONTHS[month_first[1]], int(month_first[2]))
    if parts is None:
        return value, "Date format or century is unclear; the printed value is preserved."
    try:
        return date(*parts).isoformat(), None
    except ValueError:
        return value, "The printed value is not a valid calendar date."


def valid_mrz_date(value: str) -> bool:
    if not re.fullmatch(r"\d{6}", value):
        return False
    try:
        date(2000 + int(value[:2]), int(value[2:4]), int(value[4:6]))
        return True
    except ValueError:
        return False


def matches_mrz_date(printed: str, mrz: str) -> bool:
    normalized, reason = normalize_date(printed)
    return reason is None and normalized.replace("-", "")[2:] == mrz
