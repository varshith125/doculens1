"""Document routing from observed headings, independently of MRZ availability."""

import re
from dataclasses import dataclass, field

from app.extractors.label_matcher import match_labels
from app.extractors.spatial_matcher import SpatialScores, spatial_candidates
from app.patterns.common import fold_text
from app.patterns.emirates_id import normalize_emirates_id
from app.schemas.models import MRZResult, OCRLine

TITLE_CONFIDENCE = 0.80
ID_TITLES = {
    "identity card", "national identity card", "resident identity card",
    "resident identity", "identification card", "national id card", "id card",
    "بطاقة الهوية", "بطاقة هوية", "بطاقة هوية مقيم",
}
PASSPORT_TITLES = {"passport", "passeport", "pasaporte", "جواز سفر", "جواز السفر"}
TRAVEL_TITLES = {
    "travel document", "refugee travel document",
    "document de voyage",
}
UAE_HEADINGS = {"united arab emirates", "الامارات العربية المتحدة"}


@dataclass
class DocumentContext:
    kind: str = "unknown"
    headings: list[OCRLine] = field(default_factory=list)
    ambiguous: bool = False


def document_context(lines: list[OCRLine]) -> dict[str, DocumentContext]:
    # Exclude values beneath nationality/name/country captions from title evidence.
    # Classification must not infer a card's issuer from its holder's nationality.
    scores: SpatialScores = {}
    value_rows = {
        id(value) for owner in lines if match_labels(owner.text)
        for value in spatial_candidates(owner, lines, scores)
    }
    contexts = {}
    for side in ("front", "back"):
        titles: dict[str, list[OCRLine]] = {"passport": [], "identity_card": [], "travel_document": []}
        uae, emirates = [], []
        for row in lines:
            if row.side != side or row.confidence < TITLE_CONFIDENCE or row.review_required:
                continue
            text = fold_text(row.text).strip(" .:")
            captions = match_labels(row.text)
            # A passport-number field, nationality value, or instruction mentioning
            # a passport is not a document title.
            if any(item.field_name == "emirates_id_number" for item in captions) or normalize_emirates_id(row.text):
                emirates.append(row)
            if captions or id(row) in value_rows:
                continue
            parts = {part.strip(" .:") for part in re.split(r"[/|·•\n]", text)}
            # A document title can precede a spaced dash and an issuer/subtitle.
            # Only accept an entire leading title, never a word inside prose.
            title = re.split(r"\s+[-–—]\s+", text, maxsplit=1)[0]
            if title in PASSPORT_TITLES | ID_TITLES | TRAVEL_TITLES:
                parts.add(title)
            if parts & PASSPORT_TITLES:
                titles["passport"].append(row)
            if parts & ID_TITLES:
                titles["identity_card"].append(row)
            if parts & TRAVEL_TITLES:
                titles["travel_document"].append(row)
            if parts & UAE_HEADINGS:
                uae.append(row)
            if parts & {"emirates id", "emirates id card"}:
                emirates.append(row)
        kinds = {kind for kind, rows in titles.items() if rows}
        # An Emirates ID number may also be printed on another document. Its
        # label must not turn a clearly titled UAE passport into an ID card.
        if uae and titles["identity_card"]:
            kinds.discard("identity_card")
            kinds.add("emirates_id")
        elif emirates and not kinds & {"passport", "travel_document"}:
            kinds.discard("identity_card")
            kinds.add("emirates_id")
        # A travel-document title is more specific than an accompanying PASSPORT.
        if "travel_document" in kinds:
            kinds.discard("passport")
        headings = [row for rows in titles.values() for row in rows] + uae + emirates
        contexts[side] = DocumentContext(
            kind=next(iter(kinds)) if len(kinds) == 1 else "unknown",
            headings=headings, ambiguous=len(kinds) > 1,
        )
    return contexts


def classify_document(
    contexts: dict[str, DocumentContext], mrzs: list[MRZResult], layout_recognized: bool,
) -> tuple[str, str]:
    has_passport_header = any(
        any(part in PASSPORT_TITLES for row in context.headings for part in re.split(r"[/|·•\n]", fold_text(row.text).strip(" .:")))
        for context in contexts.values()
    ) or any(context.kind == "passport" for context in contexts.values())
    has_td3 = any(mrz.format == "TD3" for mrz in mrzs)
    kinds = {context.kind for context in contexts.values() if context.kind != "unknown"}
    if (has_passport_header or has_td3) and "emirates_id" in kinds:
        has_id_title = any(
            any(part in ID_TITLES for row in context.headings for part in re.split(r"[/|·•\n]", fold_text(row.text).strip(" .:")))
            for context in contexts.values()
        )
        if not has_id_title:
            kinds.discard("emirates_id")
            kinds.add("passport")
    if "emirates_id" in kinds:
        kinds.discard("identity_card")
    if any(context.ambiguous for context in contexts.values()) or len(kinds) > 1:
        return "unknown", "Document headings indicate different document types. Review the uploaded sides; passport-specific number rules were not applied."
    if kinds:
        return next(iter(kinds)), "Document type identified from printed headings; an MRZ or a perfectly read identity number is not required."
    formats = {mrz.format for mrz in mrzs if mrz.checksum_valid}
    has_passport_mrz = any(
        mrz.format == "TD3" or any(line.startswith("P<") for line in mrz.raw_lines)
        for mrz in mrzs
    )
    if "TD3" in formats and formats & {"TD1", "TD2"}:
        return "unknown", "Different MRZ document families were detected; no single document type was selected."
    if "TD3" in formats or has_passport_mrz or layout_recognized:
        return "passport", "Passport layout identified from structured MRZ or corroborated printed layout evidence."
    if formats & {"TD1", "TD2"}:
        return "identity_card", "Identity-document layout identified from a checked TD1/TD2 MRZ."
    return "unknown", "No document type could be established reliably. Readable labeled fields remain available."
