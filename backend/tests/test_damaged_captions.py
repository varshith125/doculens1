import pytest

from app.extractors.label_matcher import match_label


@pytest.mark.parametrize("text,field", [
    ("Da e of Birth:", "date_of_birth"),        # a dropped letter
    ("suing Date /y", "date_of_issue"),         # first letters clipped at the edge
    ("Expry Date:", "date_of_expiry"),          # a typo
    ("Dote of lssue/", "date_of_issue"),        # two OCR confusions in a long caption
    ("Middio Namey/Deuxckime Prénom", "middle_names"),  # three errors in a long caption
])
def test_damaged_caption_is_recognized_and_marked_approximate(text, field):
    match = match_label(text)
    assert match is not None
    assert match.field_name == field
    assert match.approximate


def test_damaged_caption_keeps_its_inline_value():
    match = match_label("Da e of Birth: 31/07/1973")
    assert (match.field_name, match.value) == ("date_of_birth", "31/07/1973")


@pytest.mark.parametrize("text", [
    "Riniki Bhuyan Sarma",   # a name, no caption punctuation
    "Abu Dhabi",
    "Partner M",
    "Golden Card",
    "Signature/",            # a real caption, but not a known field
])
def test_values_are_not_mistaken_for_damaged_captions(text):
    assert match_label(text) is None
