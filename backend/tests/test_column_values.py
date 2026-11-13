"""Side-by-side caption columns, relationship lines under names, and ICAO document codes."""

from app.extractors.column_split import split_column_values
from app.extractors.field_extractor import extract_fields
from app.schemas.models import OCRLine
from app.services.output import prepare_output


def row(text, x, y, width, height=12, confidence=0.99):
    return OCRLine(text=text, confidence=confidence,
                   bounding_box=[[x, y], [x + width, y], [x + width, y + height], [x, y + height]])


def column_header():
    # Three captions side by side, and one OCR box holding all three values.
    return [row("type", 270, 66, 23, 9), row("code", 307, 66, 23, 9),
            row("2 nationaliteit/nationality/nationalité", 355, 66, 153, 9),
            row("P UTO Utopian", 272, 77, 206, 22)]


def test_merged_box_is_split_by_the_caption_columns_above_it():
    pieces = split_column_values(column_header())
    values = [line.text for line in pieces[3:]]
    assert values == ["P", "UTO", "Utopian"]
    lefts = [min(p[0] for p in line.bounding_box) for line in pieces[3:]]
    assert lefts == sorted(lefts)
    assert all("P UTO Utopian" in line.recognition_note for line in pieces[3:])


def test_nationality_receives_only_its_own_column():
    fields = prepare_output(extract_fields(column_header()))["fields"]
    assert fields["nationality"].value == "Utopian"


def test_a_value_under_one_caption_is_never_split():
    lines = [row("Surname", 0, 0, 80, 9), row("Sex", 400, 0, 40, 9), row("VAN DER BERG", 0, 12, 160, 20)]
    assert [line.text for line in split_column_values(lines)] == [line.text for line in lines]


def test_relationship_line_is_kept_apart_from_the_surname():
    result = extract_fields([
        row("Surname", 0, 0, 120, 9), row("Example", 0, 12, 120, 20),
        row("S/O Morgan Example", 0, 36, 200, 20),
        row("Given names", 0, 70, 120, 9), row("Alex", 0, 82, 120, 20),
    ])
    assert result["fields"]["surname"].value == "Example"
    note = next(f for f in result["other_fields"] if f.field_name == "surname_note")
    assert note.value == "S/O Morgan Example"


def test_printed_icao_code_identifies_a_passport_without_title_or_mrz():
    result = extract_fields([row("Type", 0, 0, 40, 9), row("P", 0, 12, 20, 20),
                             row("Surname", 0, 50, 80, 9), row("Example", 0, 62, 120, 20)])
    assert result["document_type"] == "passport"
    assert "ICAO document code" in result["document_type_reason"]


def test_digits_in_letter_only_mrz_positions_are_read_as_letters():
    from app.extractors.mrz_parser import parse_mrz

    result = parse_mrz(["P<UT0C0STA<<MATE0<<<<<<<<<<<<<<<<<<<<<<<<<<<",
                        "YG07158054UTO6605289M3106165<<<<<<<<<<<<<<<2"])
    assert result.checksum_valid is True
    assert (result.fields["issuing_country"], result.fields["surname"], result.fields["given_names"]) == (
        "UTO", "COSTA", "MATEO")
    assert result.raw_lines[0] == "P<UT0C0STA<<MATE0<<<<<<<<<<<<<<<<<<<<<<<<<<<"


def test_crop_that_slices_text_is_detected():
    from app.services.pipeline import crop_cuts_text

    sliced = [row("lu passeport: X1", 0, 10 + 40 * i, 300) for i in range(4)] + [
        row("Clear line", 120, 200 + 40 * i, 300) for i in range(4)]
    margins = [row("Clear line", 60, 10 + 40 * i, 300) for i in range(8)]
    assert crop_cuts_text(sliced, (900, 1000, 3)) is True
    assert crop_cuts_text(margins, (900, 1000, 3)) is False


def test_unlisted_printed_nationality_takes_its_code_from_a_checked_mrz():
    from app.extractors.mrz_parser import check_digit

    number = "YG0715805"
    second = number + check_digit(number) + "UTO" + "660528" + check_digit("660528") + "M"
    second += "310616" + check_digit("310616") + "<" * 14 + "<"
    second += check_digit(second[:10] + second[13:20] + second[21:43])
    first = "P<UTOCOSTA<<MATEO".ljust(44, "<")
    fields = prepare_output(extract_fields([
        row("Nationality", 0, 0, 120, 9), row("Utopian", 0, 12, 120, 20),
        row(first, 0, 500, 800, 20), row(second, 0, 530, 800, 20),
    ]))["fields"]
    assert fields["nationality"].value == "Utopian"
    assert fields["nationality"].code == "UTO"
    assert fields["nationality"].validation["code_from_checked_mrz"] is True
