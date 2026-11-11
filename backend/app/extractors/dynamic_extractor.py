"""Multilingual, evidence-grounded layout association over existing OCR output.

Meaning comes from a local learned encoder. Geometry proposes relationships;
semantic, OCR and typography scores rank them. Close alternatives are retained
as evidence rather than resolved by document templates or MRZ contents.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from statistics import median

import numpy as np

from app.extractors.association_assignment import resolve_associations
from app.extractors.label_matcher import is_caption, match_label, match_labels
from app.extractors.layout_graph import TextBlock, group_text, intervenes, relation
from app.extractors.semantic_model import TextEncoder
from app.patterns.common import fold_text
from app.patterns.dates import normalize_date
from app.schemas.field_semantics import FIELD_MEANINGS, PRIMARY_FIELDS
from app.schemas.models import CaptionFragment, Evidence, FieldValue, OCRLine

DOC_TITLES = {
    "passport", "passeport", "pasaporte", "جواز سفر", "جواز السفر",
    "identity card", "national identity card", "resident identity card",
    "resident identity", "identification card", "national id card", "id card",
    "بطاقة الهوية", "بطاقة هوية", "بطاقة هوية مقيم",
    "travel document", "refugee travel document", "refugee travet-document",
    "document de voyage",
    "united arab emirates", "الامارات العربية المتحدة",
    "emirates id", "emirates id card",
}


# The weakest schema similarity at which printed wording counts as a document heading.
MIN_HEADING_MEANING = .53


def caption_relevance(captions: list[str], encoder: TextEncoder) -> list[float]:
    """Strongest similarity of each caption to any known document concept."""
    if not captions:
        return []
    reference = _schema_vectors(encoder)
    forms = encoder.encode([form for caption in captions for form in (caption, caption.casefold())])
    scores = (forms @ reference.T).max(axis=1)
    return [float(max(scores[2 * i], scores[2 * i + 1])) for i in range(len(captions))]


@dataclass(frozen=True)
class Meaning:
    field: str
    score: float
    margin: float
    english: float


@dataclass(frozen=True)
class Heading:
    block: TextBlock
    fragments: tuple[TextBlock, ...]
    meaning: Meaning

    @property
    def sources(self) -> frozenset[int]:
        return frozenset().union(*(part.sources for part in self.fragments))


@dataclass(frozen=True)
class Association:
    heading: int
    value: TextBlock
    score: float
    direction: str


@dataclass
class VisualResult:
    fields: dict[str, FieldValue]
    other: dict[str, FieldValue]
    warnings: list[str]


@lru_cache(maxsize=2)
def _schema_vectors(encoder: TextEncoder) -> np.ndarray:
    # Only public schema definitions are cached, never document text.
    concepts = [key.replace("_", " ") for key in FIELD_MEANINGS] + list(FIELD_MEANINGS.values())
    return encoder.encode(concepts)


def interpret_blocks(blocks: list[TextBlock], encoder: TextEncoder) -> tuple[dict[int, Meaning], dict[int, np.ndarray]]:
    """Normalize meaning to output concepts using embeddings, never alias tests.

    Split caption translation runs only for interpretation. The actual OCR
    block and all possible values are left untouched.
    """
    keys = list(FIELD_MEANINGS)
    variants = {b.id: [b.text] + [part.strip() for part in re.split(r"[/|·•\n]", b.text)
                                if part.strip() and part.strip() != b.text] for b in blocks}
    texts = list(dict.fromkeys(form for group in variants.values() for text in group for form in (text, text.casefold())))
    reference = _schema_vectors(encoder)
    by_text = dict(zip(texts, encoder.encode(texts), strict=True))
    meanings = {}
    for block in blocks:
        scores = np.asarray([np.maximum(by_text[t] @ reference.T, by_text[t.casefold()] @ reference.T)
                             for t in variants[block.id]])
        scores = np.maximum(scores[:, :len(keys)], scores[:, len(keys):])
        # English evidence is preferred when a combined OCR box contains
        # translations; otherwise use their strongest semantic interpretation.
        representative = 0
        if len(variants[block.id]) > 2:
            representatives = list(range(1, len(variants[block.id])))
            english = {i: encoder.english_probability(variants[block.id][i]) for i in representatives}
            likely_english = max(representatives, key=lambda i: english[i])
            representative = (likely_english if english[likely_english] >= .25 else
                              max(representatives, key=lambda i: float(np.max(scores[i]))))
        # Multiple languages should support the same concept. Independent
        # headings in a single unsplittable OCR box do not locate their values.
        ranked = np.argsort(-scores[representative])
        best = int(ranked[0])
        score = float(scores[representative, best])
        margin = score - float(scores[representative, ranked[1]])
        parts = scores[1:]
        if len(parts) > 1:
            confident = [int(np.argmax(p)) for p in parts if float(np.max(p)) >= .75
                         and float(np.sort(p)[-1] - np.sort(p)[-2]) >= .08]
            if len(set(confident)) > 1:
                margin = 0
        matched = None
        for v in variants[block.id]:
            m = match_label(v)
            if m and m.field_name in keys and not m.value.strip():
                matched = m
                break
        if matched:
            best = keys.index(matched.field_name)
            score = max(float(scores[representative, best]), 1.0)
            margin = max(margin, 0.5)
        elif keys[best] == "nationality" and re.search(r"\b(?:passport office|department|ministry|authority|office of)\b", fold_text(block.text)):
            score = 0.5
            margin = 0.0
        meanings[block.id] = Meaning(keys[best], score, margin, encoder.english_probability(block.text))
    return meanings, {b.id: by_text[b.text] for b in blocks}


def heading_strength(block: TextBlock, meaning: Meaning, neighbors: list[TextBlock]) -> float:
    """Relative typography is supporting evidence, never a font-size rule."""
    if not neighbors:
        return meaning.score
    nearby_height = median(b.height for b in neighbors)
    typography = max(-1., min(1., math.log2(nearby_height / block.height)))
    punctuation = .04 if block.text.rstrip().endswith((":", "：")) else 0
    return max(0., min(1., meaning.score + .05 * typography + punctuation))


def build_headings(blocks: list[TextBlock], meanings: dict[int, Meaning], vectors: dict[int, np.ndarray]) -> list[Heading]:
    scales = {side: median(b.height for b in blocks if b.side == side) for side in {b.side for b in blocks}}
    strengths = {}
    for block in blocks:
        nearby = [b for b in blocks if relation(block, b, scales[block.side]) is not None]
        strengths[block.id] = heading_strength(block, meanings[block.id], nearby)
    # A moderately similar proper noun is often the answer to a much stronger
    # nearby caption. Classify that relationship jointly instead of treating
    # every schema-nearest string as a heading. No script/case/name blacklist.
    value_like = {
        block.id for block in blocks
        if (match_label(block.text) is None or bool(match_label(block.text).value.strip()))
        and (meanings[block.id].score < .78
            or re.search(r"\b(?:passport office|department|ministry|office of|authority\s+(?:for|of))\b", fold_text(block.text)))
        and any(meanings[other.id].score >= .75
                and (link := relation(other, block, scales[block.side])) is not None
                and link.distance <= 3 and link.alignment >= .6 for other in blocks)
    }
    # Grouped captions win only when meaning is improved; unrecognized words
    # do not get consumed merely because they share a baseline with a caption.
    ordered = sorted(blocks, key=lambda b: (-strengths[b.id], -len(b.sources), b.id))
    chosen: list[TextBlock] = []
    occupied: set[int] = set()
    for block in ordered:
        meaning = meanings[block.id]
        if fold_text(block.text).strip(" .:") in DOC_TITLES:
            continue
        if len(set(m.field_name for m in match_labels(block.text))) > 1:
            continue
        if strengths[block.id] < .57 or meaning.score < MIN_HEADING_MEANING or block.sources & occupied or block.id in value_like:
            continue
        chosen.append(block)
        occupied.update(block.sources)
    # Equivalent neighboring captions become one heading. The strongest
    # identifiable English representation is preferred; all originals remain.
    headings = []
    consumed = set()
    for block in chosen:
        if block.id in consumed:
            continue
        group = [block]
        for other in chosen:
            if other.id == block.id or other.id in consumed or other.side != block.side:
                continue
            valid_links = [(p, link) for p in group if (link := relation(p, other, scales[block.side])) is not None and link.distance <= 2.5]
            if not valid_links:
                continue
            parent, link = min(valid_links, key=lambda x: x[1].distance)
            similarity = max(float(vectors[p.id] @ vectors[other.id]) for p in group)
            same_meaning = meanings[other.id].field == meanings[block.id].field
            uncertain_translation = (min(meanings[other.id].margin, meanings[block.id].margin) < .06
                                     and abs(meanings[other.id].english - meanings[block.id].english) > .1)
            if similarity < .60 or not (same_meaning or uncertain_translation):
                continue
            if any(other.text.casefold() == p.text.casefold() for p in group):
                continue
            # A value or another field between captions breaks the group.
            if any(intervenes(parent, other, candidate, link.direction) for candidate in blocks
                   if len(candidate.sources) == 1 and candidate not in group and candidate.id not in consumed):
                continue
            group.append(other)
            consumed.add(other.id)
        preferred = max(group, key=lambda b: (meanings[b.id].english, meanings[b.id].score))
        meaning = meanings[preferred.id]
        if len(group) > 1:
            meaning = replace(meaning, score=max(meanings[b.id].score for b in group),
                              margin=max(meanings[b.id].margin for b in group))
        headings.append(Heading(preferred, tuple(group), meaning))
    return headings


def evidence(block: TextBlock, heading: Heading | None = None) -> list[Evidence]:
    fragments = [CaptionFragment(raw_text=row.text, bounding_box=row.bounding_box)
                 for part in heading.fragments for row in part.rows] if heading else []
    result = []
    for row in block.rows:
        observations = row.observations or [None]
        for observation in observations:
            result.append(Evidence(
                source="visual", raw_text=observation.text if observation else row.text,
                side=row.side, confidence=observation.confidence if observation else row.confidence,
                bounding_box=(observation.bounding_box or row.bounding_box) if observation else row.bounding_box,
                recognition_method=observation.method if observation else None,
                associated_label=heading.block.rows[0].text if (heading and heading.block.rows) else (heading.block.text if heading else None),
                label_bounding_box=heading.block.rows[0].bounding_box if heading else None,
                label_fragments=fragments, candidate_value=block.text if heading else None,
            ))
    return result


def value_block(value: TextBlock, owner: Heading, blocks: list[TextBlock],
                headings: list[Heading], scale: float) -> TextBlock:
    """Join tightly wrapped answers using geometry, independent of field type.

    Each fragment remains verbatim in evidence. A newline in the assembled
    reading denotes an observed line boundary, not a guessed spelling.
    """
    label_sources = frozenset().union(*(heading.sources for heading in headings))
    parts = [value]
    occupied = set(value.sources)
    while True:
        previous = parts[-1]
        eligible = []
        for block in blocks:
            if block.side != value.side or block.sources & (label_sources | occupied):
                continue
            if is_caption(block.text):
                continue
            gap = block.box[1] - previous.box[3]
            if not (-.1 * scale <= gap <= .65 * scale):
                continue
            if abs(block.box[0] - previous.box[0]) > .4 * scale:
                continue
            if max(block.height, previous.height) / min(block.height, previous.height) > 1.3:
                continue
            if any(intervenes(previous, block, part, "below") for heading in headings for part in heading.fragments):
                continue
            own_links = [link for part in owner.fragments if (link := relation(part, block, scale))]
            if not own_links:
                continue
            own = max(link.proximity * link.alignment for link in own_links)
            rival = max((link.proximity * link.alignment for heading in headings if heading is not owner
                         for part in heading.fragments if (link := relation(part, block, scale)) and link.direction == "below"), default=0.)
            if rival >= own - .05:
                continue
            eligible.append(block)
        if not eligible:
            break
        eligible.sort(key=lambda b: (b.box[1], -len(b.sources)))
        next_line = eligible[0]
        if any(abs(b.box[1] - next_line.box[1]) <= .3 * scale and not b.sources & next_line.sources
               for b in eligible[1:]):
            break
        parts.append(next_line)
        occupied.update(next_line.sources)
    if len(parts) == 1:
        return value
    return replace(value, text="\n".join(p.text for p in parts),
                   sources=frozenset(occupied), rows=tuple(r for p in parts for r in p.rows),
                   confidence=min(p.confidence for p in parts),
                   box=(min(p.box[0] for p in parts), min(p.box[1] for p in parts),
                        max(p.box[2] for p in parts), max(p.box[3] for p in parts)))


def _is_compatible_value(field: str, text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if field == "country_code":
        return re.fullmatch(r"[A-Za-z]{3}|[Dd](?:<<)?", text) is not None
    if field in {"issuing_country", "nationality"}:
        folded = fold_text(text)
        if any(char.isdecimal() for char in text):
            return False
        if any(bad in folded for bad in ("authority", "identity", "citizenship", "customs", "security", "ministry", "department", "office", "card", "resident", "passport")):
            return False
        return True
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
            if re.fullmatch(r"[A-Za-z]{0,3}\d{4,}", text):
                return False
            return not any(normalize_date(text, order)[1] is None for order in ("dmy", "mdy"))
        return True
    return True


def associate(headings: list[Heading], blocks: list[TextBlock], meanings: dict[int, Meaning],
              inline: dict[int, TextBlock]) -> list[list[Association]]:
    if not blocks:
        return [[] for _ in headings]
    scales = {side: median(b.height for b in blocks if b.side == side) for side in {b.side for b in blocks}}
    heading_sources = frozenset().union(*(heading.sources for heading in headings))
    candidates: list[list[Association]] = []
    for index, heading in enumerate(headings):
        edges = []
        if heading.block.id in inline:
            value = inline[heading.block.id]
            if _is_compatible_value(heading.meaning.field, value.text):
                ocr = min(heading.block.confidence, value.confidence)
                score = round(.34 * heading.meaning.score + .50 + .16 * ocr, 3)
                edges.append(Association(index, value, score, "inline"))
        else:
            for value in blocks:
                if value.sources & heading_sources:
                    continue
                if is_caption(value.text) or (fold_text(value.text).strip(" .:") in DOC_TITLES and heading.meaning.field != "issuing_country"):
                    continue
                if (m := match_label(value.text)) is not None and not m.value:
                    continue
                if not _is_compatible_value(heading.meaning.field, value.text):
                    continue
                links = [(part, relation(part, value, scales[part.side])) for part in heading.fragments]
                links = [(part, link) for part, link in links if link is not None]
                if not links:
                    continue
                anchor, link = max(links, key=lambda item: item[1].proximity * item[1].alignment)
                if any(intervenes(anchor, value, part, link.direction)
                       for other in headings if other is not heading for part in other.fragments):
                    continue
                # Do not skip an intervening answer on the same axis.
                if any(intervenes(anchor, value, other, link.direction) for other in blocks
                       if len(other.sources) == 1 and not other.sources & heading_sources):
                    continue
                typography = max(-1., min(1., math.log2(value.height / anchor.height)))
                ocr = min(value.confidence, anchor.confidence)
                # Scores are ranking measures, not calibrated probabilities.
                score = (.34 * heading.meaning.score + .26 * link.proximity
                         + .19 * link.alignment + .16 * ocr + .05 * typography)
                if heading.meaning.field in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
                    if any(normalize_date(value.text, o)[1] is None for o in ("dmy", "mdy")):
                        score += .06
                # A possible translated caption may not become a high-confidence
                # value even if its own semantic normalization was inconclusive.
                value_meaning = meanings[value.id]
                if value_meaning.score >= .70 and value_meaning.field == heading.meaning.field:
                    score -= .22
                grouped = value_block(value, heading, blocks, headings, scales[value.side])
                edges.append(Association(index, grouped, max(0., min(1., score)), link.direction))
        candidates.append(edges)
    # The single text box each heading matches best. A merged block that also
    # swallows a neighbouring heading's own box spans two fields, so it yields
    # to the heading's own single box.
    own = [max((e for e in edges if len(e.value.sources) == 1), key=lambda e: e.score, default=None)
           for edges in candidates]
    for index, edges in enumerate(candidates):
        if own[index] is not None:
            claimed = frozenset().union(*(
                other.value.sources for j, other in enumerate(own)
                if j != index and other is not None and other.score >= own[index].score - .05
                and not other.value.sources & own[index].value.sources))
            edges = [e for e in edges if len(e.value.sources) == 1
                     or not (e.value.sources & claimed and own[index].value.sources <= e.value.sources)]
        # Overlapping word-group hypotheses represent the same evidence, not
        # independent corroboration. Preserve disjoint alternatives only.
        distinct = []
        for edge in sorted(edges, key=lambda e: (-e.score, -len(e.value.sources), e.value.id)):
            if not any(edge.value.sources & prior.value.sources for prior in distinct):
                distinct.append(edge)
        candidates[index] = distinct
    # Learn a weak reading-direction prior from unambiguous local relationships.
    votes = Counter(edges[0].direction for edges in candidates if edges
                    and edges[0].score >= .78 and (len(edges) == 1 or edges[0].score - edges[1].score > .12))
    total = sum(votes.values())
    if total >= 2:
        # A penalty, not a bonus: scores already at the ceiling must still separate.
        strength = .035 if total < 3 else .10
        # Only a heading with candidates on more than one side needs the tie-break;
        # a document may legitimately mix "value beside" and "value below" rows.
        candidates = [[edge if len({e.direction for e in edges}) < 2 else
                       replace(edge, score=max(0., edge.score - strength * (1 - votes[edge.direction] / total)))
                       for edge in edges] for edges in candidates]
    return [sorted(edges, key=lambda e: (-e.score, e.value.id)) for edges in candidates]


def _caption_after_noise(text: str) -> bool:
    """True when a known caption appears only after leading text that is not one."""
    if match_label(text) is not None:
        return False
    words = text.split()
    return any((found := match_label(" ".join(words[i:]))) is not None and not found.value.strip()
               for i in range(1, len(words)))


def extract_visual(lines: list[OCRLine], encoder: TextEncoder) -> VisualResult:
    blocks = group_text(lines)
    if not blocks:
        return VisualResult({}, {}, [])
    # These are hypotheses until the prefix is semantically identified. Keep
    # the exact source box; splitting a string does not locate individual words.
    inline = {}
    prefixes = []
    for block in blocks:
        match = re.search(r"[:：]", block.text)
        if match and block.text[:match.start()].strip() and block.text[match.end():].strip():
            prefix = replace(block, id=len(blocks) + len(prefixes), text=block.text[:match.start()].strip())
            prefixes.append(prefix)
            if len(block.rows) > 1:
                pref_rows = tuple(r for r in block.rows if r.text.strip().rstrip(":") == prefix.text.strip() or r.text.strip() == prefix.text.strip())
                val_rows = tuple(r for r in block.rows if r not in pref_rows)
                prefix = replace(prefix, rows=pref_rows or prefix.rows)
                inline[prefix.id] = replace(block, text=block.text[match.end():].lstrip(),
                                            rows=val_rows or block.rows,
                                            inline_parent=prefix.id)
            else:
                inline[prefix.id] = replace(block, text=block.text[match.end():].lstrip(), inline_parent=prefix.id)
    all_blocks = blocks + prefixes
    meanings, vectors = interpret_blocks(all_blocks, encoder)
    valid_prefixes = [b for b in prefixes if meanings[b.id].score >= .75 and meanings[b.id].margin >= .035]
    replaced = frozenset().union(*(b.sources for b in valid_prefixes))
    blocks = [b for b in blocks if not b.sources & replaced] + valid_prefixes
    # Inline punctuation establishes a local structural relationship even when
    # there are no other OCR boxes on the page.
    headings = build_headings(blocks, meanings, vectors)
    selected = {h.block.id for h in headings}
    for block in valid_prefixes:
        if block.id not in selected:
            headings.append(Heading(block, (block,), meanings[block.id]))
    candidates = associate(headings, blocks, meanings, inline)
    assignment = resolve_associations(candidates, headings)
    fields: dict[str, FieldValue] = {}
    other: dict[str, FieldValue] = {}
    recognized = [match_label(h.block.text) is not None for h in headings]
    for index, heading in enumerate(headings):
        edges = candidates[index]
        chosen, competing = assignment[index]
        noisy_heading = _caption_after_noise(heading.block.text)
        if noisy_heading and sum(recognized) < 2:
            # Without other clearly read captions there is no evidence that this
            # damaged text is a heading at all.
            continue
        best = chosen or (edges[0] if edges else None)
        semantic_ambiguous = heading.meaning.margin < .045
        confident = bool(chosen and not semantic_ambiguous and not competing)
        if chosen:
            edges = [chosen] + [edge for edge in edges if edge is not chosen]
        value_review = bool(best and any(r.review_required for r in best.value.rows))
        heading_review = any(r.review_required for p in heading.fragments for r in p.rows)
        field = FieldValue(
            field_name=heading.meaning.field, display_label=heading.block.text,
            source="visual", value_kind="printed" if confident else "unresolved",
            value=best.value.text if confident else None,
            observed_value=best.value.text if confident else None,
            display_value=best.value.text if confident else None,
            status="detected" if confident and best.score >= .80 and best.value.confidence >= .80 else "uncertain",
            confidence=best.value.confidence if best else None,
            bounding_box=best.value.rows[0].bounding_box if confident else None,
            validation={"dynamic_layout": True, "heading_meaning_ambiguous": semantic_ambiguous,
                        "association_ambiguous": competing, "english_heading_preferred": len(heading.fragments) > 1,
                        "ocr_review_required": heading_review or value_review,
                        "value_ocr_review_required": value_review},
            reason=(f"Layout association ({best.direction}); score {best.score:.3f}, "
                    f"heading semantic margin {heading.meaning.margin:.3f}. " if best else "No nearby value found. ")
                   + ("Original OCR value preserved." if confident else
                      "Heading meaning or value association is uncertain; candidate readings remain in evidence."),
            evidence=([item for edge in edges[:4] for item in evidence(edge.value, heading)]
                      or [item for part in heading.fragments for item in evidence(part)]),
        )
        if value_review or noisy_heading:
            field.status = "uncertain"
        target = fields if field.field_name in PRIMARY_FIELDS else other
        existing = target.get(field.field_name)
        if existing is None:
            target[field.field_name] = field
        elif existing.value is None and field.value is not None:
            field.evidence.extend(existing.evidence)
            target[field.field_name] = field
        elif field.value is None and existing.value is not None:
            existing.evidence.extend(field.evidence)
        elif existing.value is not None and field.value is not None:
            if fold_text(existing.value) == fold_text(field.value):
                existing.evidence.extend(field.evidence)
                if existing.status != "detected" and field.status == "detected":
                    existing.status = "detected"
            else:
                existing_conf = existing.confidence or 0.0
                field_conf = field.confidence or 0.0
                if field_conf > existing_conf:
                    winner = field
                    loser = existing
                else:
                    winner = existing
                    loser = field
                all_evidence = list(winner.evidence)
                for item in loser.evidence:
                    if item not in all_evidence:
                        all_evidence.append(item)
                winner.evidence = all_evidence
                winner.confidence = max(existing_conf, field_conf)
                winner.status = "conflicting"
                winner.reason = "Conflicting values detected for this field across document sides or sections; candidate readings remain in evidence."
                target[field.field_name] = winner
        else:
            existing.evidence.extend(field.evidence)
    return VisualResult(fields, other, [])
