import re
import unicodedata
from dataclasses import dataclass

from app.patterns.common import ADDITIONAL_LABELS, LABEL_ALIASES, fold_text


@dataclass(frozen=True)
class LabelMatch:
    field_name: str
    value: str
    additional: bool = False
    display_label: str | None = None


def _fold_with_positions(text: str) -> tuple[str, list[int]]:
    letters, positions = [], []
    for index, char in enumerate(text):
        for part in unicodedata.normalize("NFKD", char).casefold():
            if unicodedata.combining(part):
                continue
            if part.isspace():
                if not letters or letters[-1] == " ":
                    continue
                part = " "
            letters.append(part)
            positions.append(index)
    return "".join(letters), positions


def _match_start(text: str) -> LabelMatch | None:
    text = text.strip()
    normalized, positions = _fold_with_positions(text)
    aliases = [
        (alias, name, additional)
        for additional, mapping in ((False, LABEL_ALIASES), (True, ADDITIONAL_LABELS))
        for name, values in mapping.items()
        for alias in values
    ]
    for alias, name, additional in sorted(aliases, key=lambda row: -len(row[0])):
        pattern = re.escape(fold_text(alias)).replace(r"\ ", r"\s*")
        if "." in alias:
            pattern = pattern.replace(r"\.", r"\.?\s*")
        match = re.match(pattern + r"(?=$|[\s:./#\-])", normalized)
        if match:
            suffix = text[positions[match.end() - 1] + 1 :].lstrip(" :./#-\t")
            # Bilingual captions name the same field twice before its value.
            translated = match_label(suffix) if suffix and len(suffix) < len(text) else None
            if translated and translated.field_name == name:
                suffix = translated.value
            elif translated:
                suffix = ""
            display_label = (
                alias.title()
                if alias
                in {
                    "given name",
                    "given names",
                    "first name",
                    "first names",
                    "middle name",
                    "middle names",
                    "surname",
                    "last name",
                    "family name",
                    "full name",
                }
                else None
            )
            return LabelMatch(name, suffix, additional, display_label)
    return None


def match_label(text: str) -> LabelMatch | None:
    direct = _match_start(text)
    if direct:
        return direct
    # Some bilingual captions put a non-Latin translation before the Latin label.
    for index, char in enumerate(text):
        prefix = text[:index]
        if char.isascii() and char.isalpha() and any(c.isalpha() for c in prefix):
            if not any(c.isascii() and c.isalpha() for c in prefix):
                return _match_start(text[index:])
            break
    return None


def match_labels(text: str) -> list[LabelMatch]:
    """Split combined OCR rows at explicit additional captions, preserving value spelling."""
    first = match_label(text)
    if not first:
        return []
    value = first.value
    for found in re.finditer(r"(?<=\s)\S", value):
        suffix = value[found.start() :]
        next_label = match_label(suffix)
        if not next_label or next_label.field_name == first.field_name:
            continue
        caption = suffix[: len(suffix) - len(next_label.value)] if next_label.value else suffix
        if ":" not in caption and len(caption.strip(" .:/-")) < 6:
            continue
        current = LabelMatch(
            first.field_name,
            value[: found.start()].strip(" ;|"),
            first.additional,
            first.display_label,
        )
        return [current, *match_labels(suffix)]
    return [first]


def is_caption(text: str) -> bool:
    return match_label(text) is not None
