import math
import re
import unicodedata

from app.extractors.label_matcher import LabelMatch, is_caption, match_labels
from app.extractors.typography import prominence, text_dimensions
from app.patterns.common import fold_text
from app.patterns.dates import normalize_date
from app.schemas.models import FieldValue, OCRLine

SpatialScores = dict[int, list[tuple[float, OCRLine]]]


def _fits_caption(
    label: OCRLine, value: OCRLine, *, captions: list[LabelMatch] | None = None,
) -> bool:
    """Filter impossible field types before limiting the spatial candidates."""
    if captions is None:
        captions = match_labels(label.text)
    if len(captions) != 1:
        return True
    field = captions[0].field_name
    text = value.text.strip()
    if field == "country_code":
        # Applies to a printed code caption, not to nationality wording or names.
        return re.fullmatch(r"[A-Za-z]{3}|[Dd](?:<<)?", text) is not None
    if field in {"issuing_country", "nationality"}:
        # Office names and numeric identifiers cannot be country/nationality
        # values merely because their boxes are closer to that caption.
        return not (any(char.isdecimal() for char in text) or re.search(
            r"\b(?:passport office|department|ministry|authority|office of)\b", fold_text(text),
        ))
    if field == "authority_code":
        return len(text) <= 32 and any(c.isalnum() for c in text) and all(
            c.isalnum() or c in " ._/-" for c in text
        )
    if field == "document_code":
        return re.fullmatch(r"[A-Za-z]{1,2}", text) is not None
    if field in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
        return any(char.isdecimal() for char in text)
    if field in {"place_of_birth", "place_of_origin", "place_of_issue"}:
        if not any(char.isalpha() for char in text):
            return False
        if any(char.isdecimal() for char in text):
            # District numbers can be part of a place. Exclude complete dates
            # and compact identifiers, rather than rejecting every digit.
            if re.fullmatch(r"[A-Za-z]{0,3}\d{4,}", text):
                return False
            return not any(normalize_date(text, order)[1] is None for order in ("dmy", "mdy"))
        return True
    return True


def name_continuations(
    label: OCRLine, first: OCRLine, lines: list[OCRLine], scores: SpatialScores | None = None
) -> list[OCRLine]:
    """Join consecutive, aligned name rows; stop at captions or competing columns."""
    aligned_boxes: dict[int, tuple[float, float, float, float]] = {}
    label_angle = _angle(label)

    def box(row: OCRLine) -> tuple[float, float, float, float]:
        key = id(row)
        if key not in aligned_boxes:
            aligned_boxes[key] = _aligned_bounds(row, label)
        return aligned_boxes[key]

    result = [first]
    label_left, _, _, _ = box(label)
    for _ in range(3):
        left, top, right, bottom = box(result[-1])
        height = max(1, bottom - top)
        candidates = []
        for row in lines:
            if row is label or any(row is item for item in result) or row.side != first.side:
                continue
            x1, y1, x2, y2 = box(row)
            if abs((_angle(row) - label_angle + 90) % 180 - 90) > 15:
                continue
            if not 0.75 * height <= y2 - y1 <= 1.35 * height:
                continue
            # Detectors pad boxes; wrapped baselines can have overlapping rectangles.
            if not (-height * 0.4 <= y1 - bottom <= height * 0.65):
                continue
            if (y1 + y2 - top - bottom) / 2 < height * 0.55:
                continue
            if min(abs(x1 - left), abs(x1 - label_left)) > height * 1.5:
                continue
            if is_caption(row.text) or not any(c.isalpha() for c in row.text):
                continue
            if any(
                not (
                    c.isalpha() or c.isspace()
                    or unicodedata.category(c).startswith("M")
                    or unicodedata.category(c) == "Pd"
                    or c in "',.‘’·ʼ"
                )
                for c in row.text
            ):
                continue
            # A continuation cannot also be the value of another printed heading.
            if competing_labels(label, row, lines, continuation=True, scores=scores):
                continue
            blocked = any(
                other is not label
                and other is not row
                and all(other is not part for part in result)
                and other.side == first.side
                # Even an unrecognized intervening row is a boundary. Do not
                # skip a damaged nationality caption and append its value.
                and (top + bottom) / 2 < (box(other)[1] + box(other)[3]) / 2 < (y1 + y2) / 2
                and box(other)[0] <= max(right, x2)
                and box(other)[2] >= min(left, label_left) - height
                for other in lines
            )
            if not blocked:
                candidates.append(row)
        if len(candidates) != 1:
            break
        result.append(candidates[0])
    return result


def bounds(line: OCRLine | FieldValue) -> tuple[float, float, float, float]:
    xs, ys = zip(*(line.bounding_box or []), strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _angle(line: OCRLine) -> float:
    a, b = line.bounding_box[:2]
    # The same rectangle may start at the opposite vertex after orientation correction.
    # Baseline direction must not turn "below" into "above" for an identical box.
    return (math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) + 90) % 180 - 90


def _aligned_bounds(line: OCRLine, anchor: OCRLine) -> tuple[float, float, float, float]:
    """Measure associations in the caption's baseline frame, without altering evidence."""
    angle = math.radians(_angle(anchor))
    cosine, sine = math.cos(angle), math.sin(angle)
    origin_x, origin_y = anchor.bounding_box[0]
    points = [
        (
            (x - origin_x) * cosine + (y - origin_y) * sine,
            -(x - origin_x) * sine + (y - origin_y) * cosine,
        )
        for x, y in line.bounding_box
    ]
    xs, ys = zip(*points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _spatial_scores(
    label: OCRLine, lines: list[OCRLine], scores: SpatialScores | None = None
) -> list[tuple[float, OCRLine]]:
    """Prefer nearby values; allow clear dates across a wider, unobstructed row."""
    if scores is not None and id(label) in scores:
        return scores[id(label)]

    captions = match_labels(label.text)
    rtl_caption = sum(
        unicodedata.bidirectional(c) in {"R", "AL"} for c in label.text
    ) > sum(unicodedata.bidirectional(c) == "L" for c in label.text)
    date_caption = (
        len(captions) == 1
        and captions[0].field_name in {"date_of_birth", "date_of_issue", "date_of_expiry"}
        and not captions[0].value
    )
    label_angle = _angle(label)
    aligned_boxes: dict[int, tuple[float, float, float, float]] = {}

    def box(row: OCRLine) -> tuple[float, float, float, float]:
        key = id(row)
        if key not in aligned_boxes:
            aligned_boxes[key] = _aligned_bounds(row, label)
        return aligned_boxes[key]

    left, top, right, bottom = box(label)
    height = max(1.0, text_dimensions(label)[1])
    candidates = []
    distant_dates = []
    for line in lines:
        if (line is label or line.side != label.side or is_caption(line.text)
                or "<<" in line.text or not _fits_caption(label, line, captions=captions)):
            continue
        x1, y1, x2, y2 = box(line)
        if abs((_angle(line) - label_angle + 90) % 180 - 90) > 20:
            continue
        line_height = max(1.0, y2 - y1)
        same_row = abs((y1 + y2 - top - bottom) / 2) <= max(height, line_height) * 0.6
        to_right = same_row and -height * 0.1 <= x1 - right <= height * 5
        to_left = (
            same_row and -height * 0.1 <= left - x2 <= height * 5
            and (rtl_caption or prominence(label, line) >= 0.3)
        )
        distant_date = (
            date_caption
            and not captions[0].approximate
            and label.confidence >= 0.80
            and height * 5 < x1 - right <= height * 24
            and abs((y1 + y2 - top - bottom) / 2) <= max(height, line_height) * 0.35
            and min(bottom, y2) - max(top, y1) >= min(height, line_height) * 0.5
            and abs((_angle(line) - label_angle + 90) % 180 - 90) <= 5
            # This checks whether the row contains a complete date. The user's
            # date-order setting still controls its interpretation downstream.
            and any(normalize_date(line.text, order)[1] is None for order in ("dmy", "mdy"))
        )
        to_right = to_right or distant_date
        aligned = min(abs(x1 - left), abs(x2 - right) if rtl_caption else math.inf) <= height * 1.8
        centered = left <= x1 and x2 <= right + height * 0.5
        below = (
            -height * 0.6 <= y1 - bottom <= height * 2.2
            and (aligned or centered)
            and (y1 + y2 - top - bottom) / 2 > height * 0.2
        )
        above = (
            not same_row and 0 <= top - y2 <= height * 1.2
            and (aligned or centered)
            # Above-caption layouts need a clear visual hierarchy. Equal-size
            # text above a label is usually the previous field's value.
            and prominence(label, line) >= 0.3
        )
        if not (to_right or to_left or below or above):
            continue
        # Do not jump over another row to reach a later value. Unrecognized
        # headings still occupy space and must not disappear as boundaries.
        blocked = False
        for other in lines:
            if other is label or other is line or other.side != label.side:
                continue
            if date_caption and other.text.strip() in {":", "："}:
                continue  # OCR can put the caption's colon in a separate box.
            ox1, oy1, ox2, oy2 = box(other)
            if (to_right and abs((oy1 + oy2 - top - bottom) / 2) < height
                    and right <= ox1 and ox2 <= x1):
                blocked = True
            if (to_left and abs((oy1 + oy2 - top - bottom) / 2) < height
                    and x2 <= ox1 and ox2 <= left):
                blocked = True
            if (below and (top + bottom) / 2 < (oy1 + oy2) / 2 < (y1 + y2) / 2
                    and ox1 < x2 and ox2 > x1):
                blocked = True
            if (above and (y1 + y2) / 2 < (oy1 + oy2) / 2 < (top + bottom) / 2
                    and ox1 < x2 and ox2 > x1):
                blocked = True
            if blocked:
                break
        if blocked:
            continue
        score = (
            (max(0, x1 - right) / height + 0.1)
            if to_right
            else (max(0, left - x2) / height + (0.1 if rtl_caption else 0.45)) if to_left
            else (max(0, top - y2) / height + 0.85 + abs(x1 - left) / height) if above
            else (max(0, y1 - bottom) / height + 0.2
                  + min(abs(x1 - left), abs(x2 - right) if rtl_caption else math.inf) / height)
        )
        score -= prominence(label, line)
        if distant_date:
            distant_dates.append((score, line))
        else:
            candidates.append((score, line))
    # A distant date must not displace a nearby candidate. Existing competing
    # caption checks still decide whether a date has a unique field owner.
    candidates = candidates or distant_dates
    candidates.sort(key=lambda row: row[0])
    if scores is not None:
        scores[id(label)] = candidates
    return candidates


def spatial_candidates(
    label: OCRLine, lines: list[OCRLine], scores: SpatialScores | None = None
) -> list[OCRLine]:
    candidates = _spatial_scores(label, lines, scores)
    if not candidates:
        return []
    # Similar alternatives are returned as conflicts, not resolved by confidence alone.
    best_score = candidates[0][0]
    return [line for score, line in candidates if score <= best_score + 0.35][:2]


def competing_labels(
    label: OCRLine, value: OCRLine, lines: list[OCRLine], *, continuation: bool = False,
    scores: SpatialScores | None = None,
) -> list[OCRLine]:
    """Find equally plausible owners before accepting a cross-field association."""
    own_fields = {item.field_name for item in match_labels(label.text)}
    own_score = next(
        (score for score, row in _spatial_scores(label, lines, scores) if row is value),
        math.inf,
    )
    rivals = []
    for other in lines:
        if other is label or other.side != label.side:
            continue
        labels = match_labels(other.text)
        # Captions with their own inline value already have an owner.
        if not any(not item.value and item.field_name not in own_fields for item in labels):
            continue
        alternatives = _spatial_scores(other, lines, scores)
        if not alternatives:
            continue
        for score, row in alternatives:
            if row is value and score <= alternatives[0][0] + 0.35:
                if continuation or score <= own_score + 0.35:
                    rivals.append(other)
                break
    return rivals
