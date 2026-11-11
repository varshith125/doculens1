"""Synthetic layouts are fixtures, never production extraction rules."""

import math
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.extractors.dynamic_extractor import extract_visual
from app.extractors.field_extractor import _cross_validate_printed, extract_fields
from app.extractors.layout_graph import group_text, relation
from app.extractors.semantic_model import SemanticUnavailable, get_encoder
from app.schemas.models import FieldValue, OCRLine
from app.services.output import prepare_output


def row(text, x=0, y=0, width=140, height=20, side="front", confidence=.99):
    return OCRLine(text=text, confidence=confidence, side=side,
                   bounding_box=[[x, y], [x + width, y], [x + width, y + height], [x, y + height]])


@pytest.fixture(scope="module")
def encoder():
    directory = get_settings().semantic_models_dir
    if not Path(directory, "model.onnx").is_file():
        pytest.skip("Install the local semantic model to run learned interpretation tests")
    return get_encoder(directory)


@pytest.mark.parametrize("dx,dy", [(0, 35), (0, -35), (175, 0), (-175, 0)])
@pytest.mark.parametrize("scale", [.4, 1, 3.5])
def test_four_directions_and_scale_invariance(encoder, dx, dy, scale):
    lines = [row("Surname", 300, 300), row("O’Dala-Ševic", 300 + dx, 300 + dy)]
    for line in lines:
        line.bounding_box = [[scale * x, scale * y] for x, y in line.bounding_box]
    result = extract_visual(lines, encoder)
    assert result.fields["surname"].value == "O’Dala-Ševic"


@pytest.mark.parametrize("value", ["ÉLoïse-南", "de Silva", "ŁÓDŹ·李", "Íñigo O’Neal", "AL+SA|LEM"])
def test_printed_spelling_survives_end_to_end(value, encoder):
    result = prepare_output(extract_fields([row("Surname"), row(value, y=30)]))
    field = result["fields"]["surname"]
    assert field.value == field.observed_value == field.display_value == field.raw == value


def test_equivalent_translations_are_not_values(encoder):
    lines = [row("Nom de famille"), row("Surname", y=25), row("ÉLoïse-南", y=55, height=30)]
    field = extract_visual(lines, encoder).fields["surname"]
    assert field.value == "ÉLoïse-南"
    assert field.display_label == "Surname"
    assert any(len(e.label_fragments) == 2 for e in field.evidence)


def test_semantic_paraphrase_not_in_alias_list(encoder):
    lines = [row("Where the holder was born", width=280), row("SÃO TOMÉ", y=30)]
    field = extract_visual(lines, encoder).fields["place_of_birth"]
    assert field.value == "SÃO TOMÉ"


def test_different_columns_have_independent_owners(encoder):
    lines = [row("Surname"), row("Given names", x=350), row("K’Dala", y=35), row("Éloïse", x=350, y=35)]
    result = extract_visual(list(reversed(lines)), encoder)
    assert result.fields["surname"].value == "K’Dala"
    assert result.fields["given_names"].value == "Éloïse"


def test_equal_alternatives_remain_unresolved(encoder):
    lines = [row("Surname", x=200), row("Alpha", x=25), row("Beta", x=375)]
    field = extract_visual(lines, encoder).fields["surname"]
    assert field.value is None
    assert field.status == "uncertain"
    assert field.validation["association_ambiguous"]
    assert {e.candidate_value for e in field.evidence} >= {"Alpha", "Beta"}


def test_cannot_steal_another_heading_value(encoder):
    result = extract_visual([row("Surname"), row("Nationality", y=30), row("FRENCH", y=60)], encoder)
    assert result.fields["surname"].value is None
    assert result.fields["nationality"].value == "FRENCH"


def test_unknown_semantics_never_invent_values(encoder):
    result = extract_visual([row("zxqv"), row("Q2#μ", y=30)], encoder)
    assert not any(f.value for f in result.fields.values())


def test_missing_or_opposite_side_value_is_not_associated(encoder):
    result = extract_visual([row("Surname"), row("K’Dala", y=30, side="back")], encoder)
    assert not any(f.value for f in result.fields.values())


def test_inline_value_keeps_internal_whitespace_and_punctuation(encoder):
    field = extract_visual([row("Surname: de  Silva–李", width=350)], encoder).fields["surname"]
    assert field.value == "de  Silva–李"


def test_rotation_and_grouped_heading(encoder):
    lines = [row("Place of", width=75), row("birth", x=82, width=50), row("ŁÓDŹ", y=35)]
    for line in lines:
        angle = .12
        line.bounding_box = [[x * math.cos(angle) - y * math.sin(angle),
                              x * math.sin(angle) + y * math.cos(angle)] for x, y in line.bounding_box]
    assert extract_visual(lines, encoder).fields["place_of_birth"].value == "ŁÓDŹ"


def test_multilingual_value_is_not_replaced_by_high_confidence_mrz():
    printed = FieldValue(field_name="surname", value="ŁÓDŹ·李", observed_value="ŁÓDŹ·李",
                         display_value="ŁÓDŹ·李", value_kind="printed", status="detected",
                         confidence=.88, validation={"dynamic_layout": True})
    mrz = FieldValue(field_name="surname", value="OTHER", value_kind="mrz", status="validated", confidence=.99)
    result = _cross_validate_printed(printed, mrz)
    assert result.value == result.observed_value == "ŁÓDŹ·李"
    assert result.status == "conflicting"
    assert result.validation["source_agreement"] is False


def test_semantic_unavailable_keeps_ocr_and_reports_limitation(monkeypatch):
    def unavailable(_):
        raise SemanticUnavailable("Unavailable")
    monkeypatch.setattr("app.extractors.field_extractor.get_encoder", unavailable)
    result = extract_fields([row("Surname: Test")])
    assert not result["fields"]
    assert any("semantic model" in warning for warning in result["warnings"])


def test_invalid_geometry_cannot_create_association():
    lines = [row("A"), row("B", y=30)]
    lines[1].bounding_box = []
    assert len(group_text(lines)) == 1
    assert relation(group_text([row("A")])[0], group_text([row("B", side="back")])[0], 20) is None


def test_wrapped_value_preserves_fragments_and_line_boundaries(encoder):
    lines = [row("Given names", height=10), row("ALÉX", y=15), row("de Silva", y=39)]
    field = extract_visual(lines, encoder).fields["given_names"]
    assert field.value == "ALÉX\nde Silva"
    assert [e.raw_text for e in field.evidence] == ["ALÉX", "de Silva"]


def test_wrapped_value_stops_at_next_heading(encoder):
    lines = [row("Given names", height=10), row("ALÉX", y=15),
             row("Nationality", y=39, height=10), row("FRENCH", y=55)]
    result = extract_visual(lines, encoder)
    assert result.fields["given_names"].value == "ALÉX"
    assert result.fields["nationality"].value == "FRENCH"
