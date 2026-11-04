import re
import unicodedata
from datetime import date
from typing import Literal

DateOrder = Literal["auto", "dmy", "mdy"]

ENGLISH_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

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
    "SET": 9,  # Portuguese abbreviation, including the printed SEP/SET pair.
    "SEPT": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVEMBER": 11,
    "DEC": 12,
    "DECEMBER": 12,
    "JANVIER": 1,
    "FEVRIER": 2,
    "AVRIL": 4,
    "JUILLET": 7,
    "SEPTEMBRE": 9,
    "OCTOBRE": 10,
    "NOVEMBRE": 11,
    "DECEMBRE": 12,
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
    # Irish abbreviations used alongside English months on bilingual captions.
    "BEA": 5,
    "MFO": 9,
    # Dutch month names and abbreviations, including paired printed forms.
    "JANUARI": 1,
    "FEBRUARI": 2,
    "MAA": 3,
    "MRT": 3,
    "MAART": 3,
    "MEI": 5,
    "JUNI": 6,
    "JULI": 7,
    "AUGUSTUS": 8,
    "OKT": 10,
    "OKTOBER": 10,
}


def expand_short_year(year: int) -> int:
    """Fixed century policy, independent of the current year."""
    return (1900 if year > 26 else 2000) + year


def normalize_date(
    value: str, date_order: DateOrder = "auto", *, expand_issue_year: bool = False,
) -> tuple[str, str | None]:
    """Parse printed dates; two-digit issue years require explicit opt-in."""
    from app.patterns.common import fold_text

    text = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in value)
    # Parse a working copy only; callers retain the printed spelling separately.
    text = re.sub(r"(?<=\d)[ºª](?=\s|[-/.]|$)", "", text)
    text = fold_text(text).upper().strip().replace(",", " ")
    text = re.sub(r"(?<=\d)(?:ST|ND|RD|TH|ER|E|º|ª)(?=\s|[-/.]|$)", "", text)
    text = re.sub(r"\s+DE\s+", " ", text)
    text = re.sub(r"[‐‑–—]", "-", text)
    text = re.sub(r"\s*([-/.])\s*", r"\1", text)
    text = re.sub(r"(?<=[A-Z])\.(?=\s|/|$)", "", text)
    text = re.sub(r"\s+", " ", text)
    if expand_issue_year and re.fullmatch(r"\d{6}", text):
        # Printed issue dates follow the selected day/month order, not MRZ YYMMDD.
        text = f"{text[:2]}/{text[2:4]}/{expand_short_year(int(text[4:]))}"
    if re.fullmatch(r"\d{8}", text):
        # OCR sometimes drops separators. Consider complete calendar dates only;
        # a year-first interpretation must not silently become a different year.
        candidates = [f"{text[:4]}-{text[4:6]}-{text[6:]}"]
        if date_order in {"auto", "dmy"}:
            candidates.append(f"{text[4:]}-{text[2:4]}-{text[:2]}")
        if date_order in {"auto", "mdy"}:
            candidates.append(f"{text[4:]}-{text[:2]}-{text[2:4]}")
        valid = set()
        for candidate in candidates:
            try:
                valid.add(date.fromisoformat(candidate).isoformat())
            except ValueError:
                continue
        if len(valid) == 1:
            return next(iter(valid)), None
        if valid:
            return value, "Date order is ambiguous without separators; the printed value is preserved."
        return value, "The printed value is not a valid calendar date."
    iso = re.fullmatch(r"(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})", text)
    year_pattern = r"(\d{4}|\d{2})" if expand_issue_year else r"(\d{4})"
    numeric = re.fullmatch(r"(\d{1,2})[-/. ](\d{1,2})[-/. ]" + year_pattern, text)
    named = re.fullmatch(r"(\d{1,2})[-/. ]?([A-Z]+)(?:/([A-Z]+))?[-/. ]?" + year_pattern, text)
    month_first = re.fullmatch(r"([A-Z]+)[-/. ]?(\d{1,2})[-/. ]?" + year_pattern, text)
    year_first_named = re.fullmatch(r"(\d{4})[-/. ]([A-Z]+)[-/. ](\d{1,2})", text)
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
    elif year_first_named and year_first_named[2] in MONTHS:
        parts = (int(year_first_named[1]), MONTHS[year_first_named[2]], int(year_first_named[3]))
    if parts is None:
        return value, "Date format or century is unclear; the printed value is preserved."
    year_token = numeric[3] if numeric else named[4] if named else month_first[3] if month_first else None
    if expand_issue_year and year_token is not None and len(year_token) == 2:
        parts = (expand_short_year(parts[0]), parts[1], parts[2])
    try:
        return date(*parts).isoformat(), None
    except ValueError:
        return value, "The printed value is not a valid calendar date."


def date_context_warning(value: str, field_name: str) -> str | None:
    """Flag future birth/issue readings without substituting a plausible year."""
    if field_name not in {"date_of_birth", "date_of_issue"}:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None  # Calendar parsing and ambiguity are handled by normalize_date.
    if parsed > date.today():
        return f"The printed {field_name.replace('_', ' ')} is in the future; the full year requires review."
    return None


def valid_mrz_date(value: str) -> bool:
    if not re.fullmatch(r"\d{6}", value):
        return False
    try:
        date(2000 + int(value[:2]), int(value[2:4]), int(value[4:6]))
        return True
    except ValueError:
        return False


def normalize_mrz_date_century(value: str) -> str | None:
    """Apply the fixed birth/expiry rule: 00-26 => 2000s, 27-99 => 1900s."""
    if not re.fullmatch(r"[0-9]{6}", value):
        return None
    short_year = int(value[:2])
    year = expand_short_year(short_year)
    try:
        return date(year, int(value[2:4]), int(value[4:6])).isoformat()
    except ValueError:
        return None


def display_full_date(value: str) -> str | None:
    """Format an established ISO date without locale or timezone conversions."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return f"{parsed.day:02d}-{ENGLISH_MONTHS[parsed.month - 1]}-{parsed.year:04d}"


def matches_mrz_date(printed: str, mrz: str) -> bool:
    normalized, reason = normalize_date(printed)
    return reason is None and normalized.replace("-", "")[2:] == mrz
