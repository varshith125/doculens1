import re

from app.patterns.dates import valid_mrz_date
from app.schemas.models import MRZResult, OCRLine

MRZ_ALPHABET = re.compile(r"[A-Z0-9<]+")
FORMATS = {(2, 44): "TD3", (2, 36): "TD2", (3, 30): "TD1"}


def check_digit(value: str) -> str:
    if not value or not MRZ_ALPHABET.fullmatch(value):
        raise ValueError("MRZ check digits require uppercase ICAO characters.")
    values = (
        0 if char == "<" else int(char) if char.isdigit() else ord(char) - 55 for char in value
    )
    return str(sum(number * (7, 3, 1)[index % 3] for index, number in enumerate(values)) % 10)


def _check(value: str, digit: str, *, allow_empty: bool = False) -> bool:
    if allow_empty and set(value) == {"<"} and digit in {"<", "0"}:
        return True
    return digit.isdigit() and check_digit(value) == digit


def _names(value: str) -> dict[str, str]:
    surname, _, given = value.partition("<<")
    fields = {
        "surname": " ".join(surname.replace("<", " ").split()),
        "given_names": " ".join(given.replace("<", " ").split()),
    }
    return {key: text for key, text in fields.items() if text}


def _document_number(principal: str, digit: str, optional: str) -> tuple[str, bool, str]:
    if digit != "<":
        return principal.rstrip("<"), _check(principal, digit), optional
    # TD1/TD2 continuation ends with its check digit and a mandatory filler.
    continuation = re.match(r"([A-Z0-9]+)([0-9])<", optional)
    if not continuation:
        return principal.rstrip("<"), False, optional
    full_number = principal + continuation[1]
    return full_number, _check(full_number, continuation[2]), optional[continuation.end() :]


def parse_mrz(lines: list[str]) -> MRZResult:
    """Parse exact ICAO layouts without repairing characters or padding OCR output."""
    raw = [line.strip().upper().replace(" ", "") for line in lines]
    result = MRZResult(detected=bool(raw), raw_lines=list(lines))
    if not raw:
        return result
    format_name = FORMATS.get((len(raw), len(raw[0])))
    if not format_name or any(len(line) != len(raw[0]) for line in raw):
        result.warnings.append(
            "MRZ line lengths do not match TD1, TD2 or TD3; no fields were accepted."
        )
        return result
    result.format = format_name
    if any(not MRZ_ALPHABET.fullmatch(line) for line in raw):
        result.warnings.append(
            "MRZ contains unsupported characters; no character substitutions were made."
        )
        result.checksum_valid = False
        return result

    first, second = raw[:2]
    fields = {"document_code": first[:2].rstrip("<"), "issuing_country": first[2:5].rstrip("<")}
    if format_name == "TD1":
        number, number_ok, optional = _document_number(first[5:14], first[14], first[15:30])
        fields.update(_names(raw[2]))
        fields.update(
            document_number=number,
            nationality=second[15:18].rstrip("<"),
            date_of_birth=second[:6],
            date_of_expiry=second[8:14],
        )
        sex = second[7]
        result.checks = {
            "document_number": number_ok,
            "date_of_birth": _check(second[:6], second[6]),
            "date_of_expiry": _check(second[8:14], second[14]),
            "composite": _check(
                first[5:30] + second[:7] + second[8:15] + second[18:29], second[29]
            ),
        }
        if optional.rstrip("<"):
            fields["optional_data_1"] = optional.rstrip("<")
        if second[18:29].rstrip("<"):
            fields["optional_data_2"] = second[18:29].rstrip("<")
    else:
        fields.update(_names(first[5:]))
        optional = second[28:42] if format_name == "TD3" else second[28:35]
        if format_name == "TD2":
            number, number_ok, optional = _document_number(second[:9], second[9], optional)
        else:
            number, number_ok = second[:9].rstrip("<"), _check(second[:9], second[9])
        fields.update(
            document_number=number,
            nationality=second[10:13].rstrip("<"),
            date_of_birth=second[13:19],
            date_of_expiry=second[21:27],
        )
        sex = second[20]
        result.checks = {
            "document_number": number_ok,
            "date_of_birth": _check(second[13:19], second[19]),
            "date_of_expiry": _check(second[21:27], second[27]),
            "composite": _check(second[:10] + second[13:20] + second[21:-1], second[-1]),
        }
        if format_name == "TD3":
            result.checks["optional_data"] = _check(second[28:42], second[42], allow_empty=True)
        if optional.rstrip("<"):
            fields["optional_data"] = optional.rstrip("<")
    if sex in {"M", "F"}:
        fields["sex"] = sex
    elif sex != "<":
        result.warnings.append("MRZ sex character is invalid; no sex value was accepted.")

    prefix_ok = first[0] == "P" if format_name == "TD3" else first[0] in "ACI"
    names_line = raw[2] if format_name == "TD1" else first[5:]
    result.checks["structure"] = bool(
        prefix_ok
        and re.fullmatch(r"[A-Z<]{2}", first[:2])
        and re.fullmatch(r"[A-Z]{1,3}<{0,2}", first[2:5])
        and re.fullmatch(r"[A-Z<]+", names_line)
        and re.fullmatch(r"[A-Z]{1,3}", fields["nationality"])
        and sex in {"M", "F", "<"}
    )
    for key in ("date_of_birth", "date_of_expiry"):
        if not valid_mrz_date(fields[key]):
            result.warnings.append(
                f"MRZ {key.replace('_', ' ')} is incomplete or not a valid calendar date."
            )
            result.checks[key + "_calendar"] = False
    if names_line[-1] != "<":
        result.warnings.append(
            "MRZ names may be truncated; their full spelling cannot be recovered from this zone."
        )
    result.checksum_valid = all(result.checks.values())
    if not result.checksum_valid:
        result.warnings.append(
            "MRZ validation failed. Fields remain uncertain; inspect the document."
        )
    result.fields = {key: value for key, value in fields.items() if value and set(value) != {"<"}}
    return result


def detect_mrz(lines: list[OCRLine]) -> tuple[MRZResult, list[OCRLine]]:
    """Find adjacent OCR rows; never combine the two sides of an identity card."""
    candidates = []
    for line in lines:
        text = line.text.strip().upper().replace(" ", "")
        if len(text) >= 25 and ("<" in text or MRZ_ALPHABET.fullmatch(text)):
            candidates.append((line, text))
    candidates.sort(key=lambda item: (item[0].side, min(p[1] for p in item[0].bounding_box)))
    matches: list[tuple[MRZResult, list[OCRLine]]] = []
    for index, (_, text) in enumerate(candidates):
        for count, length in ((2, 44), (2, 36), (3, 30)):
            group = candidates[index : index + count]
            if len(group) != count or len(text) != length:
                continue
            if len({line.side for line, _ in group}) != 1 or any(
                len(content) != length for _, content in group
            ):
                continue
            if text[0] not in ("P" if length == 44 else "ACI"):
                continue
            # OCR reading order alone is insufficient on busy backgrounds.
            gaps_ok = all(
                min(p[1] for p in b.bounding_box) - max(p[1] for p in a.bounding_box)
                <= 3 * max(1, max(p[1] for p in a.bounding_box) - min(p[1] for p in a.bounding_box))
                for (a, _), (b, _) in zip(group, group[1:], strict=False)
            )
            if gaps_ok:
                matches.append(
                    (parse_mrz([line.text for line, _ in group]), [line for line, _ in group])
                )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        evidence = [line for _, group in matches for line in group]
        return MRZResult(
            detected=True,
            raw_lines=[line.text for line in evidence],
            warnings=[
                "Multiple MRZ records were found on one image. Upload one document at a time; no MRZ fields were selected."
            ],
        ), evidence
    incomplete = []
    for index, (anchor, content) in enumerate(candidates):
        if "<<" not in content and not re.match(r"^[PACI]<[A-Z]{3}", content):
            continue
        group = [anchor]
        for following, text in candidates[index + 1 : index + 3]:
            previous = group[-1]
            height = max(p[1] for p in previous.bounding_box) - min(
                p[1] for p in previous.bounding_box
            )
            gap = min(p[1] for p in following.bounding_box) - max(
                p[1] for p in previous.bounding_box
            )
            if (
                following.side != anchor.side
                or gap > 3 * max(1, height)
                or not 25 <= len(text) <= 48
            ):
                break
            group.append(following)
        incomplete.extend(line for line in group if line not in incomplete)
    if incomplete:
        return MRZResult(
            detected=True,
            raw_lines=[line.text for line in incomplete],
            warnings=[
                "MRZ-like text is incomplete. Exact line lengths are required; no missing characters were invented."
            ],
        ), incomplete
    return MRZResult(), []
