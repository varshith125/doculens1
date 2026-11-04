"""Synthetic, country-independent typography and semantic association regressions."""

import math
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.extractors.field_extractor import extract_fields
from app.extractors.label_matcher import match_label
from app.extractors.spatial_matcher import spatial_candidates
from app.extractors.typography import measure_appearance, prominence
from app.schemas.models import OCRLine


def row(text, x=0, y=0, width=180, height=10, scale=1, angle=0, side="front"):
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return OCRLine(text=text, confidence=0.99, side=side, bounding_box=[
        [scale * (a * cosine - b * sine), scale * (a * sine + b * cosine)]
        for a, b in ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
    ])


def fields(lines):
    result = extract_fields(lines)
    return result["fields"] | {field.field_name: field for field in result["other_fields"]}


@pytest.mark.parametrize("scale", [0.5, 1, 3, 8])
@pytest.mark.parametrize("angle", [-15, 0, 15])
@pytest.mark.parametrize("value", ["Bern BE", "Lugano TI", "Genève GE"])
def test_origin_translation_is_not_the_value(scale, angle, value):
    label = row("Heimatort · Lieu d'origine · Luogo di attinenza", width=340, scale=scale, angle=angle)
    printed = row(value, y=16, width=95, height=22, scale=scale, angle=angle)
    field = fields([label, printed])["place_of_origin"]
    assert field.value == value
    assert field.field_name == "place_of_origin"
    assert field.evidence[0].bounding_box == printed.bounding_box
    assert field.evidence[0].associated_label == label.text


@pytest.mark.parametrize("caption,key,value", [
    ("Place of Birth", "place_of_birth", "Berlin"),
    ("Geburtsort", "place_of_birth", "Bonn"),
    ("Lieu de naissance", "place_of_birth", "Lyon"),
    ("Luogo di nascita", "place_of_birth", "Roma"),
    ("Lugar de nacimiento", "place_of_birth", "Madrid"),
    ("Local de nascimento", "place_of_birth", "Lisboa"),
    ("مكان الميلاد", "place_of_birth", "دبي"),
    ("出生地", "place_of_birth", "北京"),
    ("出生場所", "place_of_birth", "東京"),
    ("Geboorteplaats", "place_of_birth", "Utrecht"),
    ("国籍", "nationality", "日本"),
    ("氏名", "full_name", "山田 太郎"),
    ("Sobrenome", "surname", "SILVA"),
    ("ApellidoS", "surname", "GARCIA"),
    ("旅券番号", "document_number", "AB1234567"),
    ("生年月日", "date_of_birth", "12 AUG 1988"),
    ("Autoridade emissora", "issuing_authority", "MINISTERIO"),
    ("Beruf", "occupation", "INGENIEUR"),
    ("住所", "address", "東京都"),
])
def test_native_captions_extract_printed_values(caption, key, value):
    field = fields([row(caption), row(value, y=17, height=22)])[key]
    assert field.observed_value == value


@pytest.mark.parametrize("caption,key", [
    ("Geburtsort / Place of Birth / Lieu de naissance", "place_of_birth"),
    ("Profession / Professione / Profissão", "occupation"),
    ("国籍 / Nationality / Nacionalidade", "nationality"),
    ("出生地 / 出生場所 / Place of birth", "place_of_birth"),
    ("Heimatort · Lieu d’origine · Luogo di attinenza", "place_of_origin"),
])
def test_all_field_types_group_translated_headings(caption, key):
    match = match_label(caption)
    assert match.field_name == key
    assert match.value == ""
    assert match.additional == (key in {"occupation", "place_of_origin"})


@pytest.mark.parametrize("text,key,value", [
    ("出生地：北京", "place_of_birth", "北京"),
    ("氏名：山田 太郎", "full_name", "山田 太郎"),
    ("Lieu d’origine: Genève GE", "place_of_origin", "Genève GE"),
    ("Heimatort / Place of Origin: Bern BE", "place_of_origin", "Bern BE"),
])
def test_inline_values_keep_original_spelling(text, key, value):
    assert fields([row(text)])[key].value == value


def test_stacked_translation_fragments_are_one_caption():
    lines = [row("Heimatort", width=70), row("Lieu d'origine", y=13, width=95),
             row("Luogo di attinenza", y=26, width=120),
             row("Lugano TI", y=42, height=22, width=110)]
    field = fields(lines)["place_of_origin"]
    assert field.value == "Lugano TI"
    assert [part.raw_text for part in field.evidence[0].label_fragments] == [line.text for line in lines[:3]]


def test_larger_value_beats_nearby_small_unrecognized_annotation():
    label = row("Place of Birth", width=100)
    small = row("zz", x=110, width=8, height=8)
    value = row("Berlin", y=15, width=72, height=22)
    assert spatial_candidates(label, [label, small, value]) == [value]
    assert fields([label, small, value])["place_of_birth"].value == "Berlin"


def test_a_larger_unrelated_field_is_not_selected():
    lines = [row("Place of Birth", width=100), row("Berlin", y=16, height=18, width=75),
             row("Nationality", x=160, width=100), row("INDIAN", x=160, y=16, height=30, width=140)]
    actual = fields(lines)
    assert actual["place_of_birth"].value == "Berlin"
    assert actual["nationality"].value == "INDIAN"


@pytest.mark.parametrize("position", ["above", "below", "right", "left", "left_english"])
def test_value_directions(position):
    label = row("مكان الميلاد" if position == "left" else "Place of Birth", x=150, y=60, width=90)
    x, y = {"above": (150, 33), "below": (150, 77), "right": (250, 54),
            "left": (60, 54), "left_english": (60, 54)}[position]
    value = row("Berlin", x=x, y=y, width=80, height=22)
    assert fields([label, value])["place_of_birth"].value == "Berlin"


def test_larger_previous_field_value_keeps_its_owner():
    lines = [row("Place of Birth", width=110), row("Berlin", y=15, height=22, width=90),
             row("Place of Origin", y=42, width=110), row("Bonn", y=59, height=22, width=75)]
    actual = fields(lines)
    assert actual["place_of_birth"].value == "Berlin"
    assert actual["place_of_origin"].value == "Bonn"


def test_caption_alone_cannot_be_returned_as_origin():
    actual = fields([row("Heimatort · Lieu d'origine · Luogo di attinenza", width=340)])
    assert actual["place_of_origin"].value is None


def test_equal_sizes_still_use_geometry_and_opposite_sides_never_match():
    label = row("Place of Birth")
    value = row("Berlin", y=15)
    assert fields([label, value])["place_of_birth"].value == "Berlin"
    value.side = "back"
    assert fields([label, value])["place_of_birth"].value is None


def test_ambiguous_nearby_values_require_review():
    label = row("Place of Birth", width=60)
    first = row("Bonn", y=15, width=60, height=20)
    second = row("Lyon", x=66, y=-5, width=60, height=20)
    assert len(spatial_candidates(label, [label, first, second])) == 2
    assert fields([label, first, second])["place_of_birth"].value is None


def test_image_ink_measurements_are_optional_and_do_not_change_transcript():
    image = np.full((100, 320, 3), 255, dtype=np.uint8)
    cv2.putText(image, "Place", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    cv2.putText(image, "BERLIN", (10, 67), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    label = row("Place", x=7, y=5, width=80, height=22)
    value = row("BERLIN", x=7, y=39, width=125, height=34)
    measure_appearance(image, [label, value])
    assert label.appearance and value.appearance
    assert value.appearance.ink_height > label.appearance.ink_height * 1.5
    assert prominence(label, value) > 0.3
    assert "appearance" not in value.model_dump()
    assert label.text == "Place" and value.text == "BERLIN"
    measure_appearance(np.full_like(image, 255), [label, value])
    assert label.appearance is None and value.appearance is None


def test_translated_caption_followed_by_inline_value_does_not_swallow_value():
    match = match_label("Heimatort / Place of Origin / Bonn")
    assert match.field_name == "place_of_origin"
    assert match.value == "Bonn"


def test_place_can_include_a_district_number_but_not_an_unrelated_date():
    label = row("Place of Birth", width=110)
    value = row("Paris 14e", y=17, width=95, height=22)
    unrelated = row("12 AUG 1988", x=120, width=120, height=22)
    assert fields([label, value, unrelated])["place_of_birth"].value == "Paris 14e"


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("DOCULENS_TEST_REAL_OCR") != "1", reason="Opt-in local OCR models")
def test_rendered_multilingual_document_through_real_ocr():
    from PIL import Image, ImageDraw, ImageFont

    from app.services.ocr import OCRService

    font_path = Path(os.environ.get("WINDIR", "/usr/share/fonts/truetype/dejavu"))
    font_path = font_path / "Fonts/arial.ttf" if os.name == "nt" else font_path / "DejaVuSans.ttf"
    if not font_path.is_file():
        pytest.skip("Synthetic fixture font unavailable")
    image = Image.new("RGB", (1250, 480), "white")
    draw = ImageDraw.Draw(image)
    caption = ImageFont.truetype(str(font_path), 22)
    value = ImageFont.truetype(str(font_path), 42)
    draw.text((45, 30), "SYNTHETIC DOCUMENT - TEST ONLY", fill="black", font=caption)
    for y, heading, printed in [
        (110, "Heimatort / Lieu d'origine / Luogo di attinenza", "Bern BE"),
        (240, "Geburtsort / Place of Birth / Lieu de naissance", "Berlin"),
        (370, "Nacionalidade / Nationality", "PORTUGUESE"),
    ]:
        draw.text((45, y), heading, fill="black", font=caption)
        draw.text((45, y + 30), printed, fill="black", font=value)
    lines = OCRService().read(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
    actual = fields(lines)
    assert actual["place_of_origin"].value == "Bern BE"
    assert actual["place_of_birth"].value == "Berlin"
    assert actual["nationality"].value == "PORTUGUESE"
    assert any(line.appearance for line in lines)
