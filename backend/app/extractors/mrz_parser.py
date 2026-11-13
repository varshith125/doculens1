import re
from collections import defaultdict

from app.extractors.spatial_matcher import bounds
from app.patterns.common import icao_code_name
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
    if not bool(MRZ_ALPHABET.fullmatch(value)) or not digit.isdigit():
        return False
    return check_digit(value) == digit


def _names(value: str) -> dict[str, str]:
    # Some OCR reads insert one filler after the three-character issuer slot.
    # Do not consume a double filler: that can mean an empty surname.
    if value.startswith("<") and not value.startswith("<<"):
        value = value[1:]
    surname, separator, given = value.partition("<<")
    # Without the boundary, surname and given names cannot be separated safely.
    if not separator:
        return {}
    _, padding, tail = given.partition("<<")
    if padding and tail.strip("<"):
        # A damaged surname/given separator may have been mistaken for the
        # start of padding, merging both names. Do not guess either boundary.
        return {}
    fields = {}
    for key, slot in (("surname", surname), ("given_names", given)):
        name, padding, tail = slot.partition("<<")
        # Text after the start of padding, e.g. <<<CCC<, is a damaged reading.
        # Reject this component rather than deleting Cs or inventing a spelling.
        if padding and tail.strip("<"):
            continue
        # Normalize isolated digit lookalikes in names (e.g. 1->I, 0->O, 5->S, 2->Z, 8->B)
        cleaned_name = name.translate(str.maketrans({"1": "I", "0": "O", "5": "S", "2": "Z", "8": "B"}))
        text = " ".join(cleaned_name.replace("<", " ").split())
        if (text and re.fullmatch(r"[A-Z]+(?: [A-Z]+)*", text)
                and not damaged_name_text(text)):
            fields[key] = text
    return fields


def damaged_name_text(value: str) -> bool:
    """Reject obvious filler damage without stripping genuine C letters/initials."""
    return bool(
        "<" in value or ">" in value
        or re.search(r"C{3,}|(?:\bC\s+){2,}C\b", value.upper())
    )


def passport_name_slots(text: str) -> dict[str, tuple[str, int, int]]:
    """Read literal name spans for crop recovery; these are unverified candidates."""
    text = re.sub(r"\s+", "", text).upper()
    if not 15 <= len(text) <= 48 or not re.match(r"^P[A-Z<][A-Z0-9]{3}", text):
        return {}
    start = 6 if text[5:6] == "<" and text[5:7] != "<<" else 5
    separator = text.find("<<", start)
    if separator < 0:
        return {}
    given_start = separator + 2
    given_end = text.find("<<", given_start)
    # A name crop needs an observed end boundary; do not crop a truncated name.
    if given_end < 0 or given_end == given_start:
        return {}
    spans = {"surname": (start, separator), "given_names": (given_start, given_end)}
    result = {}
    for name, (left, right) in spans.items():
        value = " ".join(text[left:right].replace("<", " ").split())
        if re.fullmatch(r"[A-Z]+(?: [A-Z]+)*", value) and not damaged_name_text(value):
            result[name] = (value, left, right)
    # Filler damage beyond the first padding boundary remains in raw evidence.
    # A usable given-name token is needed to distinguish the delimiter from padding.
    return result if "given_names" in result else {}


def _recover_passport_names(result: MRZResult, lines: list[OCRLine]) -> MRZResult:
    """Recover components from corroborated actual OCR reads, never from spelling guesses."""
    if not lines or result.format not in {None, "TD3"}:
        return result
    row = lines[0]
    if not re.match(r"^P[A-Z<][A-Z]{3}", row.text.upper().replace(" ", "")):
        return result
    if result.checksum_valid and not row.review_required and row.confidence >= 0.90:
        return result
    full = [o for o in row.observations if o.field_name is None]
    original_fields = dict(result.fields)
    for name in ("surname", "given_names"):
        votes = defaultdict(list)
        for obs in full:
            slot = passport_name_slots(obs.text).get(name)
            if slot and obs.confidence >= 0.65:
                votes[slot[0]].append(obs)
        crops = defaultdict(list)
        for obs in row.observations:
            value = " ".join(obs.text.upper().strip(" <").split())
            if (obs.field_name == name and obs.confidence >= 0.85
                    and re.fullmatch(r"[A-Z]+(?: [A-Z]+)*", value)
                    and not damaged_name_text(value)):
                crops[value].append(obs)
        crop_choices = [value for value, observations in crops.items()
                        if len({o.method for o in observations}) >= 2
                        and max(o.confidence for o in observations) >= 0.95]
        chosen = None
        used_crop = False
        # A surname seen at the original fixed start and also in a delimited
        # reread has stronger boundary evidence than a possibly clipped word crop.
        raw = row.text.upper().replace(" ", "")[5:]
        if raw.startswith("<") and not raw.startswith("<<"):
            raw = raw[1:]
        if name == "surname" and row.confidence >= 0.80:
            for value, observations in votes.items():
                encoded = value.replace(" ", "<")
                if raw.startswith(encoded + "<") and any(o.confidence >= 0.80 for o in observations):
                    chosen = value
                    break
        if chosen is None and len(crop_choices) == 1:
            chosen, used_crop = crop_choices[0], True
        if chosen is None:
            ranked = sorted(votes, key=lambda v: len({o.method for o in votes[v]}), reverse=True)
            if ranked:
                first = ranked[0]
                count = len({o.method for o in votes[first]})
                runner_up = len({o.method for o in votes[ranked[1]]}) if len(ranked) > 1 else 0
                if count >= 2 and count > runner_up and max(o.confidence for o in votes[first]) >= 0.80:
                    chosen = first
        if chosen is None:
            continue
        if not result.raw_fields:
            result.raw_fields = dict(original_fields)
        result.fields[name] = chosen
        result.format = "TD3"
        result.checks.setdefault("layout", False)
        result.checks.setdefault("structure", False)
        result.checks[name + "_structure"] = True
        result.checks[name + "_reread"] = True
        result.checks[name + "_crop_reading"] = used_crop
        result.checks[name + "_reading_conflict"] = bool((set(votes) | set(crops)) - {chosen})
        # Name rereads do not make the complete record/checksums valid.
        result.checksum_valid = False
        result.warnings.append(
            f"MRZ {name.replace('_', ' ')} recovered from corroborated OCR crops; verify the spelling. "
            "Names have no check digit. Original and alternative readings are retained."
        )
    return result


def _document_number(principal: str, digit: str, optional: str) -> tuple[str, bool, str]:
    if digit != "<":
        return principal.rstrip("<"), _check(principal, digit), optional
    # TD1/TD2 continuation ends with its check digit and a mandatory filler.
    continuation = re.match(r"([A-Z0-9]+)([0-9])<", optional)
    if not continuation:
        return principal.rstrip("<"), False, optional
    full_number = principal + continuation[1]
    return full_number, _check(full_number, continuation[2]), optional[continuation.end() :]


def _partial_passport(raw: list[str], result: MRZResult) -> MRZResult:
    """Read independently delimited passport names without padding damaged rows."""
    if not 1 <= len(raw) <= 2:
        return result
    first = raw[0]
    first_trans = first[:5] + first[5:].translate(str.maketrans({"1": "I", "0": "O", "5": "S", "2": "Z", "8": "B"}))
    if not re.fullmatch(r"P[A-Z<][A-Z]{3}[A-Z<]{5,39}", first_trans) or "<<" not in first_trans[5:]:
        return result
    # A missing end filler does not shift the issuer or surname/given delimiter.
    # Interior character loss cannot be repaired or ruled out by this fallback.
    names = _names(first_trans[5:])
    result.format = "TD3"
    result.checksum_valid = False
    result.fields = {"document_code": first[:2].rstrip("<"), "issuing_country": first[2:5], **names}
    result.checks = {
        "layout": False, "structure": False, "document_code_structure": True,
        "issuing_country_structure": True,
        **{name + "_structure": True for name in names},
    }
    result.warnings.append(
        "Partial passport MRZ: only independently readable fields are exposed for review. "
        "Names have no checksum and may be truncated or misread. No characters were added."
    )
    # Numeric fields need their complete row and independent check digits.
    if len(raw) != 2 or len(raw[1]) != 44 or not MRZ_ALPHABET.fullmatch(raw[1]):
        return result
    second = raw[1]
    for name, text, digit in (
        ("document_number", second[:9], second[9]),
        ("date_of_birth", second[13:19], second[19]),
        ("date_of_expiry", second[21:27], second[27]),
    ):
        valid = _check(text, digit)
        if name != "document_number":
            valid = valid and valid_mrz_date(text)
        result.checks[name] = valid
        result.checks[name + "_structure"] = valid
        if valid and text.rstrip("<"):
            result.fields[name] = text.rstrip("<")
    aligned = all(result.checks[name] for name in ("document_number", "date_of_birth", "date_of_expiry"))
    if aligned and re.fullmatch(r"[A-Z]{3}", second[10:13]):
        result.fields["nationality"] = second[10:13]
        result.checks["nationality_structure"] = True
    if aligned and second[20] in {"M", "F"}:
        result.fields["sex"] = second[20]
        result.checks["sex_structure"] = True
    return result


def _parse_mrz(lines: list[str]) -> MRZResult:
    """Parse exact ICAO layouts without repairing characters or padding OCR output."""
    raw = [line.strip().upper().replace(" ", "") for line in lines]
    result = MRZResult(detected=bool(raw), raw_lines=list(lines))
    if not raw:
        return result
    if any(observed != interpreted for observed, interpreted in zip(lines, raw, strict=True)):
        result.warnings.append(
            "MRZ parsing normalizes letter case and spaces. The displayed raw lines remain exactly as read; no O/0 or other character repairs were made."
        )
    format_name = FORMATS.get((len(raw), len(raw[0])))
    exact_layout = bool(format_name and all(len(line) == len(raw[0]) for line in raw))
    if not exact_layout:
        result.warnings.append(
            "MRZ line lengths do not match a complete TD1, TD2 or TD3 record."
        )
        return _partial_passport(raw, result)
    result.format = format_name
    alphabet_valid = all(MRZ_ALPHABET.fullmatch(line) for line in raw)
    if not alphabet_valid:
        result.warnings.append(
            "MRZ contains unsupported characters; independently readable fields remain available for review. No character substitutions were made."
        )

    first, second = raw[:2]
    number_digit = first[14] if format_name == "TD1" else second[9]
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
        nat_code = second[10:13].translate(str.maketrans({"1": "I", "0": "O", "8": "B", "5": "S", "2": "Z"})).rstrip("<")
        if nat_code != second[10:13].rstrip("<") and len(result.raw_lines) >= 2:
            result.raw_lines[1] = second[:10] + nat_code.ljust(3, "<") + second[13:]
        fields.update(
            document_number=number,
            nationality=nat_code,
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
    surname_text, _, given_text = names_line.partition("<<")
    result.checks.update({
        "layout": exact_layout,
        # An extension marker without a readable continuation must not expose
        # the first nine characters as a complete document number.
        "document_number_structure": bool(
            MRZ_ALPHABET.fullmatch(number) and any(char.isalnum() for char in number)
            and (number_digit != "<" or (format_name in {"TD1", "TD2"} and len(number) > 9))
        ),
        "document_code_structure": bool(prefix_ok and re.fullmatch(r"[A-Z<]{2}", first[:2])),
        "issuing_country_structure": bool(re.fullmatch(r"[A-Z]{1,3}<{0,2}", first[2:5])),
        "names_structure": bool(exact_layout and re.fullmatch(r"[A-Z<]+", names_line)),
        "surname_structure": "surname" in fields,
        "given_names_structure": bool("<<" in names_line and (
            not given_text.strip("<") or "given_names" in fields
        )),
        "nationality_structure": bool(re.fullmatch(r"[A-Z]{1,3}", fields["nationality"])),
        "sex_structure": sex in {"M", "F", "<"},
    })
    result.checks["structure"] = bool(alphabet_valid) and all(
        result.checks[key] for key in (
            "layout", "document_code_structure", "issuing_country_structure",
            "names_structure", "nationality_structure", "sex_structure", "document_number_structure",
        )
    )
    if format_name != "TD1" and names_line.startswith("<") and not names_line.startswith("<<"):
        result.checks["structure"] = False
        result.warnings.append("An extra filler precedes the surname. Name fields were read after it; review the nonstandard MRZ reading.")
    for key in ("date_of_birth", "date_of_expiry"):
        result.checks[key + "_calendar"] = valid_mrz_date(fields[key])
        if not result.checks[key + "_calendar"]:
            result.warnings.append(
                f"MRZ {key.replace('_', ' ')} is incomplete or not a valid calendar date."
            )
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


def _parse_with_corrections(lines: list[str], *, document_number: str | None = None) -> MRZResult:
    original = _parse_mrz(lines)
    if original.checksum_valid or original.format is None or original.checks.get("layout") is False:
        return original
    interpreted = [list(line.strip().upper().replace(" ", "")) for line in lines]
    # Compulsory numeric positions can constrain lookalikes. Alphanumeric
    # identifiers additionally require independently associated printed evidence.
    positions = ({0: [14], 1: [*range(7), *range(8, 15), 29]} if original.format == "TD1"
                 else {1: [9, *range(13, 20), *range(21, 28), len(interpreted[1]) - 1]})
    if original.format == "TD3":
        # Empty optional data permits either < or 0; an OCR O can represent the
        # latter. The filler itself is never changed, nor is optional data.
        positions[1].append(42)
    if original.format in {"TD1", "TD2"}:
        row, start, end, digit = (0, 15, 30, 14) if original.format == "TD1" else (1, 28, 35, 9)
        if interpreted[row][digit] == "<":
            continuation = re.match(r"[A-Z0-9]+([0-9OILBSZGQ])<", "".join(interpreted[row][start:end]))
            if continuation:
                # Only the final, delimited check position is numeric. The
                # preceding continuation remains an alphanumeric identifier.
                positions.setdefault(row, []).append(start + continuation.start(1))
    confusions = {"O": "0", "I": "1", "L": "1", "B": "8", "S": "5", "Z": "2", "G": "6", "Q": "0"}
    corrections = []
    # ICAO 9303 allows only letters or < in the issuing state, nationality, sex
    # and name positions, so a digit there is a misread letter (0 for O, 5 for S).
    letters = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
    if original.format == "TD1":
        alphabetic = {0: range(2, 5), 1: [7, 15, 16, 17], 2: range(len(interpreted[2]) if len(interpreted) > 2 else 0)}
    else:
        alphabetic = {0: range(2, len(interpreted[0])), 1: [10, 11, 12, 20]}
    letter_fixes = 0
    for row, indices in alphabetic.items():
        for index in indices:
            if row < len(interpreted) and index < len(interpreted[row]) and interpreted[row][index] in letters:
                before = interpreted[row][index]
                interpreted[row][index] = letters[before]
                letter_fixes += 1
                corrections.append(f"Line {row + 1}, position {index + 1}: {before} → {letters[before]} (letters only)")
    for row, indices in positions.items():
        for index in indices:
            before = interpreted[row][index]
            if before in confusions:
                interpreted[row][index] = confusions[before]
                corrections.append(f"Line {row + 1}, position {index + 1}: {before} → {confusions[before]}")
    if (original.format == "TD3" and document_number
            and re.fullmatch(r"[A-Z0-9]{1,9}", document_number)):
        observed = "".join(interpreted[1][:9])
        # Never alter an already checked number, even if printed OCR differs.
        # Equal lengths rule out insertion, deletion or invented padding.
        if (MRZ_ALPHABET.fullmatch(observed)
                and not _check(observed, interpreted[1][9])
                and len(observed.rstrip("<")) == len(document_number)):
            changes = [(index, before, after) for index, (before, after) in enumerate(
                zip(observed, document_number, strict=False)
            ) if before != after]
            if 1 <= len(changes) <= 2 and all(
                confusions.get(before) == after or confusions.get(after) == before
                for _, before, after in changes
            ):
                for index, before, after in changes:
                    interpreted[1][index] = after
                    corrections.append(
                        f"Line 2, position {index + 1}: {before} → {after} (corroborated by labeled printed number)"
                    )
    # Letter-only positions are fixed by the standard itself; the limit applies to
    # the number of guessed digit substitutions.
    if not corrections or len(corrections) - letter_fixes > 4:
        return original
    candidate = _parse_mrz(["".join(row) for row in interpreted])
    if not candidate.checksum_valid:
        return original
    candidate.interpreted_lines = ["".join(row) for row in interpreted]
    candidate.raw_lines = list(lines)
    candidate.raw_checks = original.checks
    candidate.raw_fields = original.fields
    candidate.corrections = corrections
    candidate.warnings.append("Context-constrained MRZ OCR substitutions satisfy structure and check digits. Review the changed positions; raw lines are unchanged.")
    return candidate


def parse_mrz(lines: list[str], *, document_number: str | None = None) -> MRZResult:
    result = _parse_with_corrections(lines, document_number=document_number)
    # Country/nationality slots have no individual check digits. Check their
    # code vocabulary independently, without changing or guessing the raw code.
    for key in ("issuing_country", "nationality"):
        if key in result.fields:
            known = icao_code_name(result.fields[key], nationality=key == "nationality") is not None
            result.checks[key + "_code_known"] = known
            if not known:
                result.warnings.append(f"Unrecognized ICAO {key.replace('_', ' ')} code; review the raw MRZ. No replacement was inferred.")
    return result


def detect_mrz(
    lines: list[OCRLine], *, document_number: str | None = None,
) -> tuple[MRZResult, list[OCRLine]]:
    """Find adjacent OCR rows; never combine the two sides of an identity card."""
    candidates = []
    for line in lines:
        text = line.text.strip().upper().replace(" ", "")
        short_passport = (15 <= len(text) < 25 and re.match(r"^P[A-Z<][A-Z]{3}", text)
                          and "<<" in text[5:])
        if short_passport or (len(text) >= 25 and ("<" in text or MRZ_ALPHABET.fullmatch(text))):
            candidates.append((line, text))
    candidates.sort(key=lambda item: (item[0].side, min(p[1] for p in item[0].bounding_box)))
    if len({line.side for line, _ in candidates}) > 1:
        return MRZResult(detected=True, raw_lines=[line.text for line, _ in candidates],
                         warnings=["MRZ rows from different sides must be parsed separately."]), [line for line, _ in candidates]
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
                _adjacent_rows(a, b)
                for (a, _), (b, _) in zip(group, group[1:], strict=False)
            )
            if gaps_ok:
                matches.append(
                    (parse_mrz([line.text for line, _ in group], document_number=document_number),
                     [line for line, _ in group])
                )
    if len(matches) == 1:
        result, evidence = matches[0]
        return _recover_passport_names(result, evidence), evidence
    if len(matches) > 1:
        evidence = [line for _, group in matches for line in group]
        return MRZResult(
            detected=True,
            raw_lines=[line.text for line in evidence],
            warnings=[
                "Multiple MRZ records were found on one image. Upload one document at a time; no MRZ fields were selected."
            ],
        ), evidence
    incomplete_groups = []
    used = set()
    for index, (anchor, content) in enumerate(candidates):
        if id(anchor) in used:
            continue
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
                or not _adjacent_rows(previous, following)
                or not 25 <= len(text) <= 48
            ):
                break
            group.append(following)
        incomplete_groups.append(group)
        used.update(id(line) for line in group)
    incomplete = [line for group in incomplete_groups for line in group]
    if len(incomplete_groups) > 1:
        return MRZResult(detected=True, raw_lines=[line.text for line in incomplete],
                         warnings=["Spatially separate MRZ fragments were found; no fields were combined."]), incomplete
    if incomplete:
        partial = parse_mrz([line.text for line in incomplete])
        partial = _recover_passport_names(partial, incomplete)
        if partial.fields:
            return partial, incomplete
        return MRZResult(
            detected=True,
            raw_lines=[line.text for line in incomplete],
            warnings=[
                "MRZ-like text is incomplete. Exact line lengths are required; no missing characters were invented."
            ],
        ), incomplete
    return MRZResult(), []


def _adjacent_rows(first: OCRLine, second: OCRLine) -> bool:
    """MRZ rows must share a column, not merely follow each other in OCR order."""
    a, b = bounds(first), bounds(second)
    height = max(1, a[3] - a[1], b[3] - b[1])
    width = max(1, a[2] - a[0], b[2] - b[0])
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    return (
        first.side == second.side
        and -0.5 * height <= b[1] - a[3] <= 3 * height
        and b[1] > a[1] + 0.4 * height
        and overlap >= 0.65 * width
    )
