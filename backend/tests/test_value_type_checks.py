from app.extractors.dynamic_extractor import _is_compatible_value
from app.patterns.dates import matches_mrz_date


def test_two_digit_printed_year_agrees_with_the_same_mrz_date():
    assert matches_mrz_date("03 SEP/SEPT 93", "930903")
    assert not matches_mrz_date("03 SEP/SEPT 93", "930904")


def test_number_fields_require_a_digit():
    assert not _is_compatible_value("book_number", "VIETN")
    assert _is_compatible_value("book_number", "000100000")
    assert _is_compatible_value("file_number", "A00000000")


def test_document_code_rejects_wrapped_caption_text():
    assert _is_compatible_value("document_code", "TP")
    assert not _is_compatible_value("document_code", "TP\nEntries/Entrées\nM")
