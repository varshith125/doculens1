from app.extractors.mrz_anchor import aligned_numeric_row, anchor_printed_values
from app.extractors.mrz_parser import check_digit
from app.schemas.models import OCRLine


def numeric_row(number="L898902C3", nationality="UTO", dob="740812", sex="F", expiry="120415"):
    body = (f"{number}{check_digit(number)}{nationality}{dob}{check_digit(dob)}{sex}"
            f"{expiry}{check_digit(expiry)}" + "<" * 14 + "0")
    return body + "0"


def line(text, top, confidence=0.99):
    return OCRLine(text=text, confidence=confidence, side="front",
                   bounding_box=[[0, top], [300, top], [300, top + 20], [0, top + 20]])


def test_exact_row_is_aligned_without_changes():
    row = aligned_numeric_row(numeric_row())
    assert (row.document_numbers, row.date_of_birth, row.date_of_expiry, row.sex) == (
        ("L898902C3",), "740812", "120415", "F")


def test_one_inserted_character_keeps_dates_and_leaves_the_number_to_the_print():
    damaged = numeric_row()
    damaged = damaged[:2] + "Z" + damaged[2:-1]
    row = aligned_numeric_row(damaged)
    # Several removals satisfy the number's single check digit; the dates do not move.
    assert "L898902C3" in row.document_numbers and len(row.document_numbers) > 1
    assert (row.date_of_birth, row.date_of_expiry, row.nationality) == ("740812", "120415", "UTO")
    rows = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", damaged]
    found = {a.field: a.value for a in anchor_printed_values(rows, [line("L898902C3", 0)], "dmy")}
    assert found["document_number"] == "L898902C3"


def test_row_with_wrong_check_digits_is_not_aligned():
    row = numeric_row()
    assert aligned_numeric_row(row[:19] + str((int(row[19]) + 1) % 10) + row[20:]) is None


def test_printed_values_without_captions_are_identified_by_the_mrz():
    rows = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", numeric_row()]
    printed = [line("ERIKSSON", 0), line("ANNA MARIA", 30), line("L898902C3", 60),
               line("12 AUG 1974", 90), line("F", 120), line("16 APR 2007", 150),
               line("15 APR 2012", 180), line("UTO", 210)]
    found = {anchor.field: anchor.value for anchor in anchor_printed_values(rows, printed, "dmy")}
    assert found == {
        "surname": "ERIKSSON", "given_names": "ANNA MARIA", "document_number": "L898902C3",
        "date_of_birth": "1974-08-12", "date_of_expiry": "2012-04-15", "sex": "F",
        "country_code": "UTO", "date_of_issue": "2007-04-16", "nationality": "UTO",
    }


def test_row_passing_as_read_is_never_realigned():
    # Removing a character elsewhere may satisfy the checks by chance; the row
    # that is valid exactly as read still decides.
    for number in ("A2205222<", "L898902C3", "C19389564"):
        row = aligned_numeric_row(numeric_row(number=number, nationality="KEN"))
        assert row is not None and row.document_numbers == (number.rstrip("<"),)


def test_name_row_with_a_dropped_first_character_still_identifies_names():
    rows = ["<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", numeric_row()]
    printed = [line("ERIKSSON", 0), line("ANNA MARIA", 30), line("UTO", 60)]
    found = {anchor.field: anchor.value for anchor in anchor_printed_values(rows, printed, "dmy")}
    assert (found["surname"], found["given_names"], found["country_code"]) == (
        "ERIKSSON", "ANNA MARIA", "UTO")


def test_name_not_following_an_issuer_code_is_not_a_surname():
    rows = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", numeric_row()]
    found = {anchor.field for anchor in anchor_printed_values(rows, [line("ANNA MARIA", 0)], "dmy")}
    assert "surname" not in found and "given_names" not in found


def test_two_candidate_issue_dates_are_not_resolved_by_elimination():
    rows = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", numeric_row()]
    printed = [line("12 AUG 1974", 0), line("15 APR 2012", 30),
               line("16 APR 2007", 60), line("01 JAN 2001", 90)]
    fields = {anchor.field for anchor in anchor_printed_values(rows, printed, "dmy")}
    assert "date_of_issue" not in fields


def test_unaligned_mrz_identifies_nothing():
    rows = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "X" * 44]
    assert anchor_printed_values(rows, [line("ERIKSSON", 0)], "dmy") == []
