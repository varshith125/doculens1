import re

# These rules check syntax only. They never establish issuance or authenticity.
# UK: https://www.gov.uk/government/publications/basic-passport-checks/basic-passport-checks-accessible
# US: https://travel.state.gov/content/travel/en/passports/passport-help/next-generation-passport.html
# US legacy formats: https://www.aamva.org/d20trafficrecordssystemsdatadictionaryjson/29507.htm
PASSPORT_NUMBER_PATTERNS = {
    "GBR": r"[0-9]{9}",
    "USA": r"(?:[A-Z][0-9]{8}|[0-9]{9})",
}


def passport_number_matches(value: str, issuing_country: str) -> bool | None:
    pattern = PASSPORT_NUMBER_PATTERNS.get(issuing_country)
    return bool(re.fullmatch(pattern, value)) if pattern else None
