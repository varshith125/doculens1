"""Separate explicitly marked contact sections from holder biodata."""

import re

from app.extractors.label_matcher import match_labels
from app.extractors.spatial_matcher import bounds
from app.patterns.common import fold_text
from app.schemas.models import OCRLine


def contact_regions(lines: list[OCRLine]) -> dict[int, int]:
    regions: dict[int, int] = {}
    for header in lines:
        if not re.fullmatch(
            r"(?:emergency contact|contact in (?:an )?emergency|next of kin)\s*:?(?:\s*/.*)?",
            fold_text(header.text),
        ):
            continue
        left, top, right, bottom = bounds(header)
        height = max(1, bottom - top)
        following = [row for row in lines if row.side == header.side and bounds(row)[1] > top]
        boundaries = [
            bounds(row)[1] for row in following
            if re.fullmatch(r"passport(?:\s*/\s*(?:passeport|pasaporte))*", fold_text(row.text))
            or any(label.field_name == "document_code"
                   for label in match_labels(row.text))
        ]
        end = min(boundaries, default=float("inf"))
        section_id = id(header)
        regions[section_id] = section_id
        for row in following:
            x1, y1, _, _ = bounds(row)
            # Contact values normally extend rightward from their heading. A
            # separate distant column must not be captured by this section.
            if y1 < end and left - 2 * height <= x1 <= right + 12 * height:
                regions[id(row)] = section_id
    return regions
