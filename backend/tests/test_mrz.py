import pytest

from app.extractors.mrz_parser import check_digit, detect_mrz, parse_mrz
from app.schemas.models import OCRLine

TD3 = [
    "P<UTO" + "ERIKSSON<<ANNA<MARIA".ljust(39, "<"),
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
]
TD2 = [
    "I<UTO" + "ERIKSSON<<ANNA<MARIA".ljust(31, "<"),
    "D231458907UTO7408122F1204159<<<<<<<6",
]
TD1 = [
    "I<UTOD231458907" + "<" * 15,
    "7408122F1204159UTO" + "<" * 11 + "6",
    "ERIKSSON<<ANNA<MARIA".ljust(30, "<"),
]


@pytest.mark.parametrize(
    "value,expected", [("L898902C3", "6"), ("740812", "2"), ("120415", "9"), ("<<<<", "0")]
)
def test_icao_checksum(value, expected):
    assert check_digit(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "ABC!", "１２３"])
def test_checksum_rejects_non_icao_characters(value):
    with pytest.raises(ValueError):
        check_digit(value)


@pytest.mark.parametrize("lines,format_name", [(TD1, "TD1"), (TD2, "TD2"), (TD3, "TD3")])
def test_standard_formats(lines, format_name):
    result = parse_mrz(lines)
    assert result.format == format_name
    assert result.checksum_valid is True
    assert result.checks["composite"] is True
    assert result.fields["surname"] == "ERIKSSON"
    assert result.fields["given_names"] == "ANNA MARIA"
    assert result.fields["date_of_birth"] == "740812"
    assert "date_of_issue" not in result.fields


def test_checksum_failure_is_not_repaired():
    lines = TD3.copy()
    lines[1] = "X" + lines[1][1:]
    result = parse_mrz(lines)
    assert result.checksum_valid is False
    assert result.checks["document_number"] is False
    assert result.fields["document_number"].startswith("X")
    assert result.warnings


def test_mrz_source_characters_and_spaces_are_preserved_for_display():
    source = [TD3[0].lower(), TD3[1][:10] + " " + TD3[1][10:]]
    result = parse_mrz(source)
    assert result.raw_lines == source
    assert result.checksum_valid


def test_incomplete_mrz_preserves_adjacent_number_line_without_inventing_fields():
    source = [TD3[0][:-1], TD3[1][:-2]]
    rows = [
        OCRLine(
            text=text, confidence=0.8, bounding_box=[[0, y], [600, y], [600, y + 20], [0, y + 20]]
        )
        for text, y in zip(source, [300, 330], strict=True)
    ]
    result, evidence = detect_mrz(rows)
    assert result.raw_lines == source
    assert evidence == rows
    assert result.fields == {}
    assert result.checksum_valid is None
    assert result.warnings


@pytest.mark.parametrize("lines", [[TD3[0][:-1], TD3[1]], [TD1[0], TD1[1]], ["<" * 44, "<" * 43]])
def test_incomplete_mrz_is_never_padded(lines):
    result = parse_mrz(lines)
    assert result.detected
    assert result.fields == {}
    assert result.checksum_valid is None


def test_optional_td3_empty_check_digit_can_be_filler():
    second = TD3[1][:28] + "<" * 15
    second += check_digit(second[:10] + second[13:20] + second[21:43])
    assert parse_mrz([TD3[0], second]).checksum_valid is True


def test_invalid_sex_and_calendar_cannot_pass_on_checksums_alone():
    second = TD3[1][:13] + "991332" + check_digit("991332") + "Q" + TD3[1][21:43]
    second += check_digit(second[:10] + second[13:20] + second[21:43])
    result = parse_mrz([TD3[0], second])
    assert result.checks["composite"]
    assert result.checksum_valid is False
    assert "sex" not in result.fields


@pytest.mark.parametrize("format_name", ["TD1", "TD2"])
def test_extended_document_numbers(format_name):
    number = "ABC123456789"
    extra = number[9:] + check_digit(number) + "<"
    if format_name == "TD1":
        first = "I<UTO" + number[:9] + "<" + extra.ljust(15, "<")
        second = TD1[1][:29]
        second += check_digit(first[5:30] + second[:7] + second[8:15] + second[18:29])
        lines = [first, second, TD1[2]]
    else:
        second = number[:9] + "<" + TD2[1][10:28] + extra.ljust(7, "<")
        second += check_digit(second[:10] + second[13:20] + second[21:35])
        lines = [TD2[0], second]
    result = parse_mrz(lines)
    assert result.fields["document_number"] == number
    assert result.checksum_valid is True


def test_no_inferred_sex_for_filler():
    second = TD3[1][:20] + "<" + TD3[1][21:]
    result = parse_mrz([TD3[0], second])
    assert result.checksum_valid
    assert "sex" not in result.fields


def line(text, y, side="front"):
    return OCRLine(
        text=text,
        confidence=0.99,
        bounding_box=[[0, y], [800, y], [800, y + 20], [0, y + 20]],
        side=side,
    )


def test_detect_mrz_with_other_text():
    result, evidence = detect_mrz([line("PASSPORT", 0), line(TD3[0], 100), line(TD3[1], 125)])
    assert result.checksum_valid
    assert len(evidence) == 2


def test_mrz_lines_from_different_sides_never_combine():
    result, _ = detect_mrz([line(TD3[0], 100), line(TD3[1], 125, "back")])
    assert not result.fields


def test_spatially_distant_mrz_fragments_do_not_combine():
    result, _ = detect_mrz([line(TD3[0], 0), line(TD3[1], 1000)])
    assert not result.fields


def test_multiple_mrz_zones_on_same_image_are_not_silently_selected():
    result, _ = detect_mrz(
        [line(TD3[0], 0), line(TD3[1], 25), line(TD3[0], 200), line(TD3[1], 225)]
    )
    assert result.detected
    assert not result.fields
    assert "Multiple MRZ" in result.warnings[0]
