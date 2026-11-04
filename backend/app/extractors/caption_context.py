"""Reconstruct caption regions without changing the retained OCR transcript."""

import math
import re
from statistics import median

from app.extractors.label_matcher import match_label
from app.extractors.spatial_matcher import _aligned_bounds, _angle
from app.extractors.typography import text_dimensions
from app.patterns.common import ADDITIONAL_LABELS, LABEL_ALIASES, fold_text
from app.schemas.models import OCRLine

ALIASES = frozenset(
    fold_text(alias) for mapping in (LABEL_ALIASES, ADDITIONAL_LABELS)
    for aliases in mapping.values() for alias in aliases
)
ENGLISH_CAPTIONS = (
    "full name", "given names", "given name", "first names", "first name",
    "middle names", "middle name", "surname", "family name", "last name", "name",
    "nationality", "issuing country", "issuing state", "country code",
    "passport number", "passport no", "national id number", "personal number",
    "date of birth", "date of issue", "date of expiry", "date of expiration",
    "place of birth", "place of origin", "place of issue", "issuing authority",
)
ENGLISH_SUFFIX = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(alias) for alias in ENGLISH_CAPTIONS)
    + r")\s*:?(?:\s*)$", re.IGNORECASE,
)


def _caption_text(text: str) -> str:
    return re.sub(r"^(?:\d{1,2}[.)]?\s+)", "", fold_text(text)).strip(" :/·•|+-")


def _next_to(first: OCRLine, second: OCRLine) -> bool:
    if first.side != second.side or abs((_angle(first) - _angle(second) + 90) % 180 - 90) > 10:
        return False
    x1, y1, x2, y2 = _aligned_bounds(first, first)
    a, b, _, d = _aligned_bounds(second, first)
    height = max(1, y2 - y1)
    if not 0.65 * height <= d - b <= 1.5 * height:
        return False
    same_row = abs((b + d - y1 - y2) / 2) <= height * 0.4
    right = same_row and -height * 0.1 <= a - x2 <= height * 1.2
    wrapped = abs(a - x1) <= height * 0.8 and 0 <= b - y2 <= height * 0.65
    return right or wrapped


def _joined(parts: list[OCRLine], text: str) -> OCRLine:
    anchor = parts[0]
    boxes = [_aligned_bounds(part, anchor) for part in parts]
    x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    angle = math.radians(_angle(anchor))
    cosine, sine = math.cos(angle), math.sin(angle)
    ox, oy = anchor.bounding_box[0]
    box = [[ox + x * cosine - y * sine, oy + x * sine + y * cosine]
           for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
    return anchor.model_copy(update={
        "text": text, "bounding_box": box,
        "confidence": min(part.confidence for part in parts),
        "text_height": median(text_dimensions(part)[1] for part in parts),
        "text_width": sum(text_dimensions(part)[0] for part in parts),
        "review_required": any(part.review_required for part in parts),
    })


def _join_translations(
    rows: list[OCRLine], sources: dict[int, list[OCRLine]],
) -> list[OCRLine]:
    """Join adjacent equivalent headings using semantic and typography evidence."""
    result = list(rows)
    for original in rows:
        if not any(original is row for row in result):
            continue
        current = original
        for _ in range(7):
            first = match_label(current.text)
            if first is None or first.value:
                break
            candidates = []
            for following in result:
                anchor = sources.get(id(current), [current])[-1]
                if following is current or not _next_to(anchor, following):
                    continue
                second = match_label(following.text)
                if second is None or second.value:
                    continue
                separated = bool(re.search(r"[/·•|;+]\s*$", current.text)
                                 or re.match(r"^\s*[/·•|;+]", following.text))
                if not separated and (first.field_name != second.field_name
                                      or first.approximate or second.approximate
                                      or _caption_text(anchor.text) == _caption_text(following.text)):
                    continue
                text = current.text + (" " if separated else " / ") + following.text
                combined = match_label(text)
                if combined is None or combined.value:
                    continue
                # Mixed headings must retain separate coordinates and owners.
                group = {first.field_name, second.field_name, combined.field_name}
                if (len(group) != 1 and not group <= {"full_name", "surname"}
                        and not group <= {"first_name", "given_names"}):
                    continue
                candidates.append((following, text))
            if len(candidates) != 1:
                break
            following, text = candidates[0]
            parts = sources.get(id(current), [current]) + sources.get(id(following), [following])
            merged = _joined(parts, text)
            result = [row for row in result if row is not current and row is not following]
            result.append(merged)
            sources[id(merged)] = parts
            current = merged
    return result


def prepare_captions(lines: list[OCRLine]) -> tuple[list[OCRLine], dict[int, list[OCRLine]]]:
    """Use adjacent caption-sized fragments, never arbitrary substring searches.

    The returned rows are association-only copies. Original text/boxes remain in
    the scan's OCR list and the source map supplies exact caption evidence.
    """
    result = list(lines)
    sources: dict[int, list[OCRLine]] = {}
    for first in lines:
        initial = match_label(first.text)
        if not any(first is row for row in result):
            continue
        if initial and (initial.value or first.text.rstrip().endswith(":") or initial.field_name not in {
            "issuing_country", "country_code", "issuing_authority", "authority_code",
        }):
            continue
        prefix = _caption_text(first.text)
        if not prefix or not any(alias.startswith(prefix + " ") for alias in ALIASES):
            continue
        parts = [first]
        combined = prefix
        complete_parts: list[OCRLine] = []
        for _ in range(2):
            nearby = [row for row in result if all(row is not part for part in parts)
                      and _next_to(parts[-1], row)]
            # Two adjacent possibilities do not establish a single caption.
            if len(nearby) != 1:
                break
            following = nearby[0]
            joined_text = combined + " " + _caption_text(following.text)
            if not any(alias == joined_text or alias.startswith(joined_text + " ") for alias in ALIASES):
                break
            parts.append(following)
            combined = joined_text
            matched = match_label(combined)
            if matched and not matched.value:
                complete_parts = list(parts)
                # Prefer a complete longer caption, e.g. Issuing Country Code,
                # when OCR splits its words into three adjacent boxes.
                if not any(alias.startswith(combined + " ") for alias in ALIASES):
                    break
        if complete_parts:
            row = _joined(complete_parts, " ".join(part.text for part in complete_parts))
            result = [item for item in result if all(item is not part for part in complete_parts)]
            result.append(row)
            sources[id(row)] = complete_parts

    result = _join_translations(result, sources)

    # A clear English caption after noisy translated text needs independent
    # document and typography context; it is not a global text-substring alias.
    for original in list(result):
        if match_label(original.text) or len(original.text) > 140:
            continue
        suffix = ENGLISH_SUFFIX.search(original.text)
        if not suffix:
            continue
        prefix = _caption_text(original.text[:suffix.start()])
        if (not prefix or len(prefix.split()) > 7 or len(prefix) > 85
                or any(char.isdigit() for char in prefix)
                or any(char in prefix for char in ':"{}<>')):
            continue
        # Require other labeled fields nearby on this same document side.
        known = set()
        for other in result:
            if other.side != original.side:
                continue
            a, b, _, d = _aligned_bounds(other, original)
            _, _, right, bottom = _aligned_bounds(original, original)
            if abs((b + d) / 2) > max(bottom, 1) * 35 or abs(a) > max(right, 1) * 2:
                continue
            matched = match_label(other.text)
            if matched:
                known.add(matched.field_name)
        if len(known) < 3:
            continue
        left, _, _, bottom = _aligned_bounds(original, original)
        below = []
        for other in result:
            if other is original or other.side != original.side:
                continue
            a, b, _, d = _aligned_bounds(other, original)
            if abs(a - left) <= bottom * 1.5 and -bottom * 0.2 <= b - bottom <= bottom * 2:
                below.append((b, other, d - b))
        below.sort(key=lambda item: item[0])
        if not below or match_label(below[0][1].text) or below[0][2] < bottom * 1.15:
            continue
        row = original.model_copy(update={
            "text": suffix[1], "review_required": True,
            "recognition_note": "English caption recognized within a noisy translated heading using nearby field and text-size evidence.",
        })
        result[result.index(original)] = row
        sources[id(row)] = [original]
    return result, sources
