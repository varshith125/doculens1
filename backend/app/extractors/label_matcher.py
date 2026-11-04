import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz.distance import Levenshtein

from app.patterns.common import ADDITIONAL_LABELS, LABEL_ALIASES, fold_text

NATIONALITY_CAPTIONS = frozenset(
    "".join(fold_text(alias).split()) for alias in LABEL_ALIASES["nationality"]
)

MULTILINGUAL_CAPTIONS = {
    field: frozenset(
        re.sub(r"\s+|\([a-z]\)", "", fold_text(alias)) for alias in aliases
    )
    for field, aliases in (LABEL_ALIASES | ADDITIONAL_LABELS).items()
}


@dataclass(frozen=True)
class LabelMatch:
    field_name: str
    value: str
    additional: bool = False
    display_label: str | None = None
    approximate: bool = False


_scan_label_cache: ContextVar[dict[str, LabelMatch | None] | None] = ContextVar(
    "scan_label_cache", default=None,
)


@contextmanager
def cached_label_matches() -> Iterator[None]:
    """Reuse immutable caption matches only for the lifetime of one scan."""
    token = _scan_label_cache.set({})
    try:
        yield
    finally:
        _scan_label_cache.reset(token)


def _caption_distance(first: str, second: str) -> int:
    """Small edit distance for caption recognition only; never repair a value."""
    return Levenshtein.distance(first, second)


def _partition_caption(text: str) -> tuple[str, str, str]:
    separator = re.search(r"[:：]", text)
    if separator is None:
        return text, "", ""
    return text[:separator.start()], separator[0], text[separator.end():]


def _nationality_caption(text: str) -> LabelMatch | None:
    heading, colon, value = _partition_caption(text)
    if len(heading) > 200:
        return None
    segments = [part.strip() for part in re.split(r"[/·•|;]|\s[-–—]\s", heading) if part.strip()]
    matches = []
    for segment in segments:
        word = "".join(fold_text(segment).split())
        if word in NATIONALITY_CAPTIONS:
            matches.append(0)
            continue
        if not word.isalpha() or not 8 <= len(word) <= 24:
            continue
        # One error for a standalone caption, up to two when multiple language
        # captions independently identify the same field in this row.
        distance = min((
            _caption_distance(word, alias) for alias in NATIONALITY_CAPTIONS
            if len(alias) >= 8 and abs(len(alias) - len(word)) <= 2
            and word[:3] == alias[:3]
        ), default=3)
        if distance <= (1 if len(segments) == 1 else 2):
            matches.append(distance)
    if not matches or (len(segments) > 1 and (len(matches) < 2 or len(matches) * 2 < len(segments))):
        return None
    approximate = any(matches) or len(matches) != len(segments)
    return LabelMatch("nationality", value.strip() if colon else "",
                      display_label=heading.strip(), approximate=approximate)


def _multilingual_caption(text: str) -> LabelMatch | None:
    """Recognize a row of translated captions before parsing any inline value."""
    heading, colon, value = _partition_caption(text)
    if len(heading) > 220:
        return None
    segments = [part.strip() for part in re.split(
        r"[/·•|;+]|\s[-–—]\s|(?<=\))\s+", heading,
    ) if part.strip()]
    if len(segments) < 2:
        return None
    hits: list[tuple[str, int, str]] = []
    for segment in segments:
        word = re.sub(r"\s+|\([a-z]\)", "", fold_text(segment))
        if not word.replace("'", "").isalpha():
            continue
        options = []
        for field, aliases in MULTILINGUAL_CAPTIONS.items():
            for alias in aliases:
                if word == alias:
                    options.append((0, field, alias))
                elif len(word) >= 6 and len(alias) >= 6 and word.isascii() and alias.isascii():
                    limit = 3 if min(len(word), len(alias)) >= 12 else 2 if min(len(word), len(alias)) >= 8 else 1
                    if abs(len(word) - len(alias)) <= limit:
                        distance = _caption_distance(word, alias)
                        if distance <= limit:
                            options.append((distance, field, alias))
        if options:
            best = min(item[0] for item in options)
            closest = [item for item in options if item[0] == best]
            if len({item[1] for item in closest}) == 1:
                distance, field, alias = closest[0]
                hits.append((field, distance, alias))
    # A mixed row of different field headings needs separate coordinates.
    groups = {
        "name_caption" if field in {"full_name", "surname"}
        else "given_caption" if field in {"given_names", "first_name"}
        else field for field, _, _ in hits
    }
    if len(groups) != 1 or len(hits) < 2 or len(hits) != len(segments):
        return None
    group = next(iter(groups))
    if group == "name_caption":
        # Generic Name/Nom alone does not establish a surname. An explicit
        # surname translation such as Cognome or Surname does.
        field = "surname" if any(key == "surname" and alias != "nom" for key, _, alias in hits) else "full_name"
    elif group == "given_caption":
        field = "first_name" if any(key == "first_name" for key, _, _ in hits) else "given_names"
    else:
        field = group
    return LabelMatch(field, value.strip() if colon else "", field in ADDITIONAL_LABELS, display_label=heading.strip(),
                      approximate=any(distance for _, distance, _ in hits) or len(hits) != len(segments))


def _fold_with_positions(text: str) -> tuple[str, list[int]]:
    letters, positions = [], []
    for index, char in enumerate(text):
        for part in unicodedata.normalize("NFKD", char).casefold():
            part = part.translate(str.maketrans("’‘ʼ", "'''"))
            if unicodedata.combining(part):
                continue
            if part.isspace():
                if not letters or letters[-1] == " ":
                    continue
                part = " "
            letters.append(part)
            positions.append(index)
    return "".join(letters), positions


def _damaged_translation(text: str, aliases: tuple[str, ...]) -> bool:
    """Recognize a near-caption only after an explicit translation separator."""
    heading = text.partition(":")[0]
    word = "".join(fold_text(heading).split()).strip("./·•|;+ -")
    if not word.isalpha() or len(word) < 6:
        return False
    for alias in aliases:
        caption = "".join(fold_text(alias).split())
        limit = 2 if min(len(word), len(caption)) >= 12 else 1
        if len(caption) >= 6 and abs(len(word) - len(caption)) <= limit:
            if _caption_distance(word, caption) <= limit:
                return True
    return False


@lru_cache(maxsize=1)
def _label_patterns() -> tuple[tuple[re.Pattern[str], str, bool], ...]:
    """Compile the fixed caption vocabulary once; no document text is cached."""
    aliases = [
        (alias, name, additional)
        for additional, mapping in ((False, LABEL_ALIASES), (True, ADDITIONAL_LABELS))
        for name, values in mapping.items()
        for alias in values
    ]
    patterns = []
    for alias, name, additional in sorted(aliases, key=lambda row: -len(row[0])):
        pattern = re.escape(fold_text(alias)).replace(r"\ ", r"\s*")
        if "." in alias:
            pattern = pattern.replace(r"\.", r"\.?\s*")
        patterns.append((re.compile(pattern + r"(?=$|[\s:./#·|()\-])"), name, additional))
    return tuple(patterns)


def _match_start(text: str) -> LabelMatch | None:
    text = text.strip()
    normalized, positions = _fold_with_positions(text)
    for pattern, name, additional in _label_patterns():
        match = pattern.match(normalized)
        if match:
            remainder = text[positions[match.end() - 1] + 1 :]
            suffix = remainder.lstrip(" :：./#·•|+;-\t")
            suffix = re.sub(r"^\(\d{1,2}\)(?:\s+|$)", "", suffix)
            if (name == "issuing_authority" and normalized[:match.end()] == "authority"
                    and re.match(r"^(?:for|of)\s", fold_text(suffix))):
                # An office name such as "Authority for Identity and Citizenship"
                # is a value, not another Authority caption.
                continue
            # Bilingual captions name the same field twice before its value.
            translated = match_label(suffix) if suffix and len(suffix) < len(text) else None
            same_caption = translated and (
                translated.field_name == name
                or {name, translated.field_name} == {"first_name", "given_names"}
                or (name == "full_name" and translated.field_name == "surname"
                    and re.match(r"^\s*[/·•|+;]", remainder))
            )
            if same_caption:
                suffix = translated.value
                if (name == "full_name" and translated.field_name == "surname"
                        and fold_text(translated.display_label or "") != "nom"):
                    # An explicit surname caption resolves a generic translation.
                    name = "surname"
                if name == "given_names" and translated.field_name == "first_name":
                    name = "first_name"
            elif (re.match(r"^\s*[/·•|+;]", remainder) and translated is None
                  and (name in {"full_name", "surname", "first_name", "given_names", "middle_names"}
                       or _damaged_translation(
                           suffix, (ADDITIONAL_LABELS if additional else LABEL_ALIASES)[name],
                       ))):
                # A damaged translation of this heading is not its field value.
                # A colon can still establish the start of the printed value.
                heading, colon, inline = text.partition(":")
                return LabelMatch(name, inline.strip() if colon else "", additional,
                                  heading.strip(), approximate=True)
            # Keep the actual heading (including accents/case/bilingual captions),
            # rather than substituting the alias that was used to recognize it.
            display_label = (text[:-len(suffix)] if suffix else text).rstrip(" :./#·|-\t")
            return LabelMatch(name, suffix, additional, display_label,
                              bool(same_caption and translated.approximate))
    return None


def match_label(text: str) -> LabelMatch | None:
    cache = _scan_label_cache.get()
    if cache is not None and text in cache:
        return cache[text]
    matched = _match_label(text)
    if cache is not None and len(cache) < 4096:
        cache[text] = matched
    return matched


def _match_label(text: str) -> LabelMatch | None:
    original = text.strip()
    text = re.sub(r"^(?:\d{1,2}[.)]\s*|\d{1,2}\s+|\d{1,2}(?=[^\W\d_])|\(\d{1,2}\)\s*)", "", original)
    prefix = original[:len(original) - len(text)]
    multilingual = _multilingual_caption(text)
    if multilingual:
        return LabelMatch(multilingual.field_name, multilingual.value, multilingual.additional,
                          display_label=prefix + (multilingual.display_label or ""),
                          approximate=multilingual.approximate)
    nationality = _nationality_caption(text)
    if nationality:
        return LabelMatch(nationality.field_name, nationality.value,
                          display_label=prefix + (nationality.display_label or ""),
                          approximate=nationality.approximate)
    direct = _match_start(text)
    if direct:
        return LabelMatch(direct.field_name, direct.value, direct.additional,
                          prefix + (direct.display_label or ""), direct.approximate)
    # Recognize a supported caption within a short, explicitly separated
    # multilingual heading. Never search arbitrary prose for a name keyword.
    for separator in re.finditer(r"[/·•|;+]|\s[-–—]\s", text):
        heading_prefix = text[:separator.end()]
        if len(heading_prefix) > 100 or ":" in heading_prefix or '"' in heading_prefix:
            break
        matched = _match_start(text[separator.end():].lstrip())
        if matched:
            return LabelMatch(matched.field_name, matched.value, matched.additional,
                              prefix + heading_prefix + (matched.display_label or ""), matched.approximate)
    # Some bilingual captions put a non-Latin translation before the Latin label.
    for index, char in enumerate(text):
        prefix = text[:index]
        if char.isascii() and char.isalpha() and any(c.isalpha() for c in prefix):
            if not any(c.isascii() and c.isalpha() for c in prefix):
                matched = _match_start(text[index:])
                if matched:
                    return LabelMatch(
                        matched.field_name, matched.value, matched.additional,
                        original[:len(original) - len(text)] + prefix + (matched.display_label or ""),
                        matched.approximate,
                    )
                return None
            break
    return None


def match_labels(text: str) -> list[LabelMatch]:
    """Split combined OCR rows at explicit additional captions, preserving value spelling."""
    first = match_label(text)
    if not first:
        return []
    value = first.value
    following = match_label(value) if value else None
    if following and following.field_name != first.field_name:
        return [
            LabelMatch(first.field_name, "", first.additional, first.display_label, first.approximate),
            *match_labels(value),
        ]
    for found in re.finditer(r"(?<=\s)\S", value):
        suffix = value[found.start() :]
        next_label = match_label(suffix)
        if not next_label or next_label.field_name == first.field_name:
            continue
        caption = suffix[: len(suffix) - len(next_label.value)] if next_label.value else suffix
        if ":" not in caption and not re.search(r"[;|]\s*$", value[:found.start()]):
            # A label word occurring inside a value is not a new field. Separate
            # boxes are handled geometrically; one-box splits require a delimiter.
            continue
        current = LabelMatch(
            first.field_name,
            value[: found.start()].strip(" ;|"),
            first.additional,
            first.display_label,
            first.approximate,
        )
        return [current, *match_labels(suffix)]
    return [first]


def is_caption(text: str) -> bool:
    if match_label(text) is not None:
        return True
    if fold_text(text).strip(" :./") in {"code", "codigo"}:
        # An unqualified code heading is a boundary, not a country/office value.
        return True
    # A damaged date caption must still stop a wrapped name. This establishes
    # only a boundary, not a field label or a date value. Require a date-like
    # opening plus a near-complete supported caption at the end (OCR may have
    # joined two translated headings without a separator).
    folded = fold_text(text).strip()
    opening = re.match(r"^([a-z]{4})\s+(?:of|de|du)\s+", folded)
    if (opening and opening[1].startswith("d")
            and _caption_distance(opening[1], "date") <= 2
            and len(folded) <= 120 and not any(c.isdigit() for c in folded)):
        compact = re.sub(r"[^a-z]", "", folded)
        for field in ("date_of_birth", "date_of_issue", "date_of_expiry"):
            for alias in MULTILINGUAL_CAPTIONS[field]:
                if len(alias) < 10:
                    continue
                for size in range(max(10, len(alias) - 2), len(alias) + 3):
                    if size <= len(compact) and _caption_distance(compact[-size:], alias) <= 2:
                        return True
    # An OCR-damaged heading may no longer match an alias. Its caption
    # punctuation still makes it a boundary, not a nearby field's value.
    stripped = text.strip()
    return bool(
        any(char.isalpha() for char in stripped)
        and (stripped.endswith(":") or re.match(r"^[/|]\s*[^\W\d_]", stripped))
    )
