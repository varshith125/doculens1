import re

EMIRATES_ID_PATTERN = re.compile(r"(?<![\w\d])784(?:[ -]?\d){12}(?![\w\d])", re.ASCII)


def find_emirates_ids(text: str) -> list[str]:
    return [re.sub(r"[ -]", "", match.group()) for match in EMIRATES_ID_PATTERN.finditer(text)]


def normalize_emirates_id(value: str) -> str | None:
    digits = re.sub(r"[ -]", "", value.strip())
    if re.fullmatch(r"784\d{12}", digits, re.ASCII):
        return digits
    return None
