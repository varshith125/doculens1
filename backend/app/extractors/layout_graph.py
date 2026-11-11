"""Scale-independent OCR grouping and spatial relations, without field knowledge."""

import math
from dataclasses import dataclass
from statistics import median

from app.schemas.models import OCRLine


@dataclass(frozen=True)
class TextBlock:
    id: int
    text: str
    rows: tuple[OCRLine, ...]
    sources: frozenset[int]
    box: tuple[float, float, float, float]
    side: str
    height: float
    confidence: float
    inline_parent: int | None = None


@dataclass(frozen=True)
class Relation:
    direction: str
    proximity: float
    alignment: float
    distance: float


def block_box(rows: tuple[OCRLine, ...], angle: float = 0) -> tuple[float, float, float, float]:
    points = [(x * math.cos(angle) + y * math.sin(angle),
               -x * math.sin(angle) + y * math.cos(angle))
              for row in rows for x, y in row.bounding_box]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def group_text(lines: list[OCRLine]) -> list[TextBlock]:
    """Group tight same-baseline OCR fragments; retain singletons as hypotheses.

    Do not fabricate per-word coordinates for text delivered as one OCR box.
    Invalid boxes remain in the transcript but cannot establish relationships.
    """
    blocks = []
    for side in dict.fromkeys(row.side for row in lines):
        valid = [(i, row) for i, row in enumerate(lines) if row.side == side and row.text.strip()
                 and len(row.bounding_box) >= 4
                 and all(len(p) == 2 and all(math.isfinite(v) for v in p) for p in row.bounding_box)]
        angles = [math.atan2(r.bounding_box[1][1] - r.bounding_box[0][1],
                             r.bounding_box[1][0] - r.bounding_box[0][0]) for _, r in valid]
        angle = median(angles) if angles else 0
        singles = []
        for index, row in valid:
            box = block_box((row,), angle)
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            height = row.text_height or (row.appearance.ink_height if row.appearance else box[3] - box[1])
            block = TextBlock(len(blocks), row.text, (row,), frozenset({index}), box,
                              side, height, row.confidence)
            blocks.append(block)
            singles.append(block)
        # Each row cluster is anchored to its first baseline (no transitive drift).
        clusters: list[list[TextBlock]] = []
        for block in sorted(singles, key=lambda b: (b.box[1], b.box[0])):
            cluster = next((c for c in clusters if abs((c[0].box[1] + c[0].box[3]) / 2
                           - (block.box[1] + block.box[3]) / 2) <= min(c[0].height, block.height) * .4), None)
            if cluster is None:
                clusters.append([block])
            else:
                cluster.append(block)
        for cluster in clusters:
            ordered = sorted(cluster, key=lambda b: b.box[0])
            for start in range(len(ordered)):
                parts = [ordered[start]]
                for following in ordered[start + 1:start + 5]:
                    previous = parts[-1]
                    gap = following.box[0] - previous.box[2]
                    if not (-.15 <= gap / min(previous.height, following.height) <= .8):
                        break
                    if max(previous.height, following.height) / min(previous.height, following.height) > 1.5:
                        break
                    parts.append(following)
                    rows = tuple(row for part in parts for row in part.rows)
                    blocks.append(TextBlock(
                        len(blocks), " ".join(p.text for p in parts), rows,
                        frozenset().union(*(p.sources for p in parts)), block_box(rows, angle),
                        side, median(p.height for p in parts), min(p.confidence for p in parts),
                    ))
    return blocks


def _row_angle(row: OCRLine) -> float:
    if len(row.bounding_box) < 2:
        return 0.0
    return math.degrees(math.atan2(
        row.bounding_box[1][1] - row.bounding_box[0][1],
        row.bounding_box[1][0] - row.bounding_box[0][0],
    ))


def _block_angle(block: TextBlock) -> float:
    if not block.rows:
        return 0.0
    return median(_row_angle(r) for r in block.rows)


def relation(label: TextBlock, value: TextBlock, scale: float) -> Relation | None:
    if label.side != value.side or label.sources & value.sources:
        return None
    label_angle = _block_angle(label)
    value_angle = _block_angle(value)
    if abs((label_angle - value_angle + 90) % 180 - 90) > 15:
        return None
    ax, ay, ar, ab = label.box
    bx, by, br, bb = value.box
    vertical_overlap = max(0., min(ab, bb) - max(ay, by)) / min(ab - ay, bb - by)
    horizontal_overlap = max(0., min(ar, br) - max(ax, bx)) / min(ar - ax, br - bx)
    choices = []
    if vertical_overlap >= .35:
        gap = max(0., bx - ar, ax - br)
        choices.append((gap / scale, vertical_overlap,
                        "right" if bx + br >= ax + ar else "left"))
    if horizontal_overlap >= .25:
        gap = max(0., by - ab, ay - bb)
        edge_alignment = max(math.exp(-abs(ax - bx) / scale), math.exp(-abs(ar - br) / scale))
        choices.append((gap / scale, .6 * horizontal_overlap + .4 * edge_alignment,
                        "below" if by + bb >= ay + ab else "above"))
    if not choices:
        return None
    distance, alignment, direction = min(choices, key=lambda item: item[0])
    if distance > 8:
        return None
    return Relation(direction, math.exp(-distance / 3), alignment, distance)


def intervenes(label: TextBlock, value: TextBlock, other: TextBlock, direction: str) -> bool:
    if other.side != label.side or other.sources & (label.sources | value.sources):
        return False
    a, b, c = label.box, value.box, other.box
    if direction in {"above", "below"}:
        if direction == "below" and c[1] >= b[1] - 2:
            return False
        if direction == "above" and c[3] <= b[3] + 2:
            return False
        middle = (c[1] + c[3]) / 2
        low, high = sorted(((a[1] + a[3]) / 2, (b[1] + b[3]) / 2))
        corridor = min(c[2], max(a[2], b[2])) > max(c[0], min(a[0], b[0]))
        overlap = (min(c[2], a[2]) > max(c[0], a[0])) or (min(c[2], b[2]) > max(c[0], b[0])) or (min(c[2], a[2], b[2]) > max(c[0], a[0], b[0]))
        return low < middle < high and corridor and overlap
    if direction == "right" and c[0] >= b[0] - 2:
        return False
    if direction == "left" and c[2] <= b[2] + 2:
        return False
    middle = (c[0] + c[2]) / 2
    low, high = sorted(((a[0] + a[2]) / 2, (b[0] + b[2]) / 2))
    corridor = min(c[3], max(a[3], b[3])) > max(c[1], min(a[1], b[1]))
    overlap = (min(c[3], a[3]) > max(c[1], a[1])) or (min(c[3], b[3]) > max(c[1], b[1])) or (min(c[3], a[3], b[3]) > max(c[1], a[1], b[1]))
    return low < middle < high and corridor and overlap
