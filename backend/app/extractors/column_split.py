"""Split one OCR box that runs across several side-by-side caption columns.

Detectors often merge a row of short values ("P NLD Nederlandse") into one box
when their captions ("type", "code", "nationality") stand side by side above
them. Each word is returned to the column whose caption it sits under, using
only geometry. The original OCR line is left untouched for review.
"""

import re

import numpy as np

from app.extractors.label_matcher import is_caption, match_label
from app.extractors.spatial_matcher import bounds
from app.schemas.models import OCRLine

# Characters that join translations of one caption ("Name / Nom").
SEPARATORS = frozenset("/|·•")


def _columns(line: OCRLine, lines: list[OCRLine]) -> list[OCRLine]:
    """Captions on the nearest caption row directly above ``line``, left to right."""
    left, top, right, bottom = bounds(line)
    height = max(1.0, bottom - top)
    above = []
    for other in lines:
        if other is line or other.side != line.side or not is_caption(other.text):
            continue
        x1, _, x2, y2 = bounds(other)
        gap = top - y2
        center = (x1 + x2) / 2
        if -0.3 * height <= gap <= 1.5 * height and left - 0.5 * height <= center <= right:
            above.append(other)
    if len(above) < 2:
        return []
    # Keep only the caption row nearest the value; a row higher up is another field.
    nearest = max(bounds(row)[3] for row in above)
    row = sorted((c for c in above
                  if abs(bounds(c)[3] - nearest) <= 0.6 * max(1.0, bounds(c)[3] - bounds(c)[1])),
                 key=lambda c: bounds(c)[0])
    # Translations of one caption ("Name" "/ Nom") are one column, not two.
    columns: list[OCRLine] = []
    for caption in row:
        if columns and _same_caption(columns[-1], caption):
            continue
        columns.append(caption)
    return columns if len(columns) >= 2 else []


def _same_caption(previous: OCRLine, caption: OCRLine) -> bool:
    if caption.text.lstrip()[:1] in SEPARATORS or previous.text.rstrip()[-1:] in SEPARATORS:
        return True
    first, second = match_label(previous.text), match_label(caption.text)
    return bool(first and second and first.field_name == second.field_name)


def _piece(line: OCRLine, text: str, start: int, end: int) -> OCRLine:
    """A sub-line covering characters [start, end) of ``line``, by proportional width."""
    box = np.asarray(line.bounding_box, dtype=float)
    a, b = start / len(line.text), end / len(line.text)
    top = [box[0] + (box[1] - box[0]) * a, box[0] + (box[1] - box[0]) * b]
    bottom = [box[3] + (box[2] - box[3]) * b, box[3] + (box[2] - box[3]) * a]
    return line.model_copy(update={
        "text": text,
        "bounding_box": np.round([top[0], top[1], bottom[0], bottom[1]], 2).tolist(),
        "observations": [],
        "recognition_note": "Split from a wider OCR box by the caption columns above it; "
                            f"the original reading was {line.text!r}.",
    })


def split_column_values(lines: list[OCRLine]) -> list[OCRLine]:
    result = []
    for line in lines:
        tokens = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", line.text)]
        columns = _columns(line, lines) if len(tokens) >= 2 and not is_caption(line.text) else []
        if not columns:
            result.append(line)
            continue
        left, _, right, _ = bounds(line)
        edges = [bounds(c)[0] for c in columns]
        groups: dict[int, list[tuple[int, int, str]]] = {}
        for start, end, word in tokens:
            center = left + (right - left) * ((start + end) / 2) / len(line.text)
            column = max([0] + [i for i, edge in enumerate(edges) if edge <= center])
            groups.setdefault(column, []).append((start, end, word))
        if len(groups) < 2:
            result.append(line)
            continue
        for words in groups.values():
            start, end = words[0][0], words[-1][1]
            result.append(_piece(line, line.text[start:end], start, end))
    return result
