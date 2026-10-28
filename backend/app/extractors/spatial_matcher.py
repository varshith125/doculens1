import math

from app.extractors.label_matcher import is_caption
from app.schemas.models import OCRLine


def name_continuations(label: OCRLine, first: OCRLine, lines: list[OCRLine]) -> list[OCRLine]:
    """Join consecutive, aligned name rows; stop at captions or competing columns."""

    def box(row: OCRLine) -> tuple[float, float, float, float]:
        return _aligned_bounds(row, label)

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
            # Detectors pad boxes; wrapped baselines can have overlapping rectangles.
            if not (-height * 0.4 <= y1 - bottom <= height * 1.2):
                continue
            if (y1 + y2 - top - bottom) / 2 < height * 0.55:
                continue
            if min(abs(x1 - left), abs(x1 - label_left)) > height * 1.5:
                continue
            if is_caption(row.text) or not any(c.isalpha() for c in row.text):
                continue
            if any(not (c.isalpha() or c.isspace() or c in "-'.’") for c in row.text):
                continue
            blocked = any(
                other is not label
                and other.side == first.side
                and is_caption(other.text)
                and top < box(other)[1] <= y2
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


def bounds(line: OCRLine) -> tuple[float, float, float, float]:
    xs, ys = zip(*line.bounding_box, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _angle(line: OCRLine) -> float:
    a, b = line.bounding_box[:2]
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


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


def spatial_candidates(label: OCRLine, lines: list[OCRLine]) -> list[OCRLine]:
    """Restrict association to a nearby row or the next aligned value below."""

    def box(row: OCRLine) -> tuple[float, float, float, float]:
        return _aligned_bounds(row, label)

    left, top, right, bottom = box(label)
    height = max(1.0, bottom - top)
    candidates = []
    for line in lines:
        if line is label or line.side != label.side or is_caption(line.text) or "<<" in line.text:
            continue
        x1, y1, x2, y2 = box(line)
        if abs((_angle(line) - _angle(label) + 90) % 180 - 90) > 20:
            continue
        line_height = max(1.0, y2 - y1)
        same_row = abs((y1 + y2 - top - bottom) / 2) <= max(height, line_height) * 0.6
        to_right = same_row and -height * 0.1 <= x1 - right <= height * 5
        aligned = abs(x1 - left) <= height * 1.8
        centered = left <= x1 and x2 <= right + height * 0.5
        below = (
            -height * 0.6 <= y1 - bottom <= height * 2.2
            and (aligned or centered)
            and (y1 + y2 - top - bottom) / 2 > height * 0.2
        )
        if not (to_right or below):
            continue
        # Do not jump over another label to reach a later value.
        blocked = False
        for other in lines:
            if other is label or other.side != label.side or not is_caption(other.text):
                continue
            ox1, oy1, ox2, oy2 = box(other)
            if to_right and abs((oy1 + oy2 - top - bottom) / 2) < height and right <= ox1 < x1:
                blocked = True
            if below and top < oy1 < y1 and abs(ox1 - left) < height * 1.8:
                blocked = True
        if blocked:
            continue
        score = (
            (max(0, x1 - right) / height + 0.1)
            if to_right
            else (max(0, y1 - bottom) / height + 0.2 + abs(x1 - left) / height)
        )
        candidates.append((score, line))
    candidates.sort(key=lambda row: row[0])
    if not candidates:
        return []
    # Similar alternatives are returned as conflicts, not resolved by confidence alone.
    best_score = candidates[0][0]
    return [line for score, line in candidates if score <= best_score + 0.35][:2]
