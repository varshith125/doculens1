import re
import unicodedata
from functools import lru_cache

from app.patterns.multilingual import MULTILINGUAL_LABELS

LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "document_number": (
        "passport num",
        "passport #",
        "passport no de passeport",
        "no de passeport",
        "no du passeport",
        "no. du passeport",
        "no de pasaporte",
        "no. de pasaporte",
        "passport number",
        "passport no",
        "passport no.",
        "passeport no",
        "passeport no.",
        "pass-nr",
        "pass-nr.",
        "pass nr",
        "pass nr.",
        "passport n°",
        "passport nr",
        "document number",
        "document no",
        "documentnummer",
        "paspoortnummer",
        "numero de passeport",
        "رقم جواز السفر",
    ),
    "emirates_id_number": (
        "emirates id number",
        "رقم الهوية",
    ),
    "national_id_number": (
        "id number",
        "id no",
        "identity number",
        "national id number",
        "d number",
        "d no",
    ),
    "surname": (
        "surname",
        "family name",
        "achternaam",
        "geslachtsnaam",
        "cognome",
        "last name",
        "nom de famille",
        "nom",
        "nom de naissance",
        "de naissance",
        "geburtsname",
        "name at birth",
        "apellidos",
        "sloinne",
        "nachname",
        "prijmeni",
        "eponymo",
        "nume",
        "apelido",
        "nazwisko",
        "фамилия",
        "اسم العائلة",
        "اللقب",
    ),
    "given_names": (
        "given names",
        "given name",
        "voornamen",
        "voornaam",
        "vorname",
        "vornamen",
        "given name(s)",
        "vorname(n)",
        "prenom(s)",
        "nome", "nomi", "prenum", "prenums",
        "prenoms",
        "prenom",
        "nombres",
        "forenames",
        "first names",
        "tusainmneacha",
        "leadain",
        "jmeno",
        "onoma",
        "prenume",
        "imie",
        "الاسم الاول",
    ),
    "first_name": ("first name", "first names"),
    "full_name": ("full name", "name", "naam", "الاسم الكامل", "الاسم"),
    "middle_names": (
        "middle names", "middle name", "middlo nameydeuxime prenom",
    ),
    "nationality": (
        "nationality", "nationalite", "nacionalidad", "nazionalita",
        "nationalitat", "cittadinanza", "naziunalitad", "nacionalidade",
        "nationaliteit", "staatsangehorigkeit", "statni obcanstvi",
        "statna prislusnost", "εθνικότητα", "ιθαγένεια",
        "জাতীয়তা", "राष्ट्रीयता", "الجنسية",
    ),
    "issuing_country": (
        "issuing country",
        "country of issue",
        "issuing state",
        "issuing state or organization",
        "pays emetteur",
        "pays de delivrance", "pais emisor", "pais de expedicion",
        "ausstellender staat", "stato emittente",
        "دولة الاصدار",
    ),
    "country_code": (
        "issuing country code", "issuing state code", "country code",
        "code du pays", "code de l'etat emetteur", "codigo del pais",
        "landercode", "رمز دولة الاصدار",
    ),
    "date_of_birth": (
        "date of birth",
        "birth date",
        "dob",
        "d.o.b",
        "birthdate",
        "geboortedatum",
        "geburtsdatum",
        "data di nascita",
        "date de naissance",
        "fecha de nacimiento",
        "date of birth date de naissance",
        "تاريخ الميلاد",
    ),
    "place_of_birth": (
        "place of birth",
        "birthplace",
        "geboorteplaats",
        "geburtsort",
        "lieu de naissance",
        "place of bith",
        "place of bithy",
        "lugar de nacimiento",
        "مكان الميلاد",
    ),
    "sex": ("sex", "sexe", "sexo", "gender", "geslacht", "geschlecht", "الجنس"),
    "date_of_issue": (
        "date of issuance",
        "issuance date",
        "issued date",
        "doi",
        "d.o.i",
        "date of issue",
        "issue date",
        "issuing date",
        "issued on",
        "datum van afgifte",
        "afgiftedatum",
        "ausstellungsdatum",
        "aussteliungsdatum",
        "date de delivrance",
        "date d'emission",
        "date d emission",
        "fecha de expedicion",
        "date of issue date de delivrance",
        "تاريخ الاصدار",
    ),
    "date_of_expiry": (
        "valid till",
        "valid to",
        "expiry",
        "expiration",
        "date of expiry",
        "date of explry",
        "expiry date",
        "expiration date",
        "date of expiration",
        "valid until",
        "gultig bis",
        "gültig bis",
        "geldig tot",
        "vervaldatum",
        "date d expiration",
        "date d'expiration",
        "fecha de caducidad",
        "fecha de vencimiento",
        "تاريخ الانتهاء",
    ),
    "issuing_authority": (
        "issuing authority", "authority", "issuing office",
        "autorite de delivrance", "autorite emettrice", "autorite",
        "autoridad expedidora", "autoridad emisora", "autoridad",
        "ausstellende behorde", "behorde", "autorita rilasciante",
        "جهة الاصدار", "سلطة الاصدار",
    ),
}

ADDITIONAL_LABELS: dict[str, tuple[str, ...]] = {
    "occupation": ("occupation", "profession", "المهنة"),
    "employer": ("employer", "جهة العمل"),
    "place_of_issue": (
        "place of issue", "lieu de delivrance", "lieu d'emission",
        "lugar de expedicion", "lugar de emision", "ausstellungsort",
        "luogo di rilascio", "issuing place", "issued at", "مكان الاصدار",
    ),
    "personal_number": ("personal number", "personal no", "persoonsnummer"),
    "authority_code": (
        "issuing authority code", "authority code", "code d'autorite",
        "code de l'autorite", "codigo de autoridad", "behordencode", "رمز جهة الاصدار",
    ),
    "card_number": ("card number", "card no", "cardnumbr", "cardnbr", "رقم البطاقة"),
    "previous_passport_number": ("previous passport no", "previous passport number"),
    "file_number": ("file number", "numero de dossier"),
    "book_number": ("book number", "book no", "registre"),
    "father_name": ("father's name", "father name"),
    "mother_name": ("mother's name", "mother name"),
    "spouse_name": ("spouse's name", "spouse name"),
    "contact_relationship": ("relationship",),
    "permanent_address": ("permanent address",),
    "address": ("address",),
    "telephone_number": ("telephone no", "telephone number",),
    "document_code": ("type", "tipo", "typ", "typeycategorie"),
    "place_of_origin": ("place of origin", "lieu d'origine", "luogo di origine", "heimatort"),
}

for _field, _aliases in MULTILINGUAL_LABELS.items():
    _registry = LABEL_ALIASES if _field in LABEL_ALIASES else ADDITIONAL_LABELS
    _registry[_field] = tuple(dict.fromkeys((*_registry.get(_field, ()), *_aliases)))


COUNTRY_ALIASES = {
    "nederland": "NLD",
    "nederlands": "NLD",
    "nederlandse": "NLD",
    "dutch": "NLD",
    "india": "IND",
    "inde": "IND", "الهند": "IND", "الهندي": "IND", "الهندية": "IND",
    "indian": "IND",
    "ind": "IND",
    "united arab emirates": "ARE",
    "الامارات العربية المتحدة": "ARE", "اماراتي": "ARE", "اماراتية": "ARE",
    "emirati": "ARE",
    "uae": "ARE",
    "are": "ARE",
    "united states of america": "USA",
    "united states": "USA",
    "الولايات المتحدة الامريكية": "USA", "امريكي": "USA", "امريكية": "USA",
    "american": "USA",
    "usa": "USA",
    "united kingdom": "GBR",
    "royaume-uni": "GBR", "المملكة المتحدة": "GBR", "بريطاني": "GBR", "بريطانية": "GBR",
    "british citizen": "GBR",
    "british": "GBR",
    "gbr": "GBR",
    "canadian": "CAN", "canadienne": "CAN", "canadien": "CAN",
    "australian": "AUS", "saudi": "SAU", "saudi arabian": "SAU",
    "singaporean": "SGP", "german": "D",
    "france": "FRA",
    "french": "FRA",
    "francaise": "FRA",
    "fra": "FRA",
    "germany": "D",
    "deutsch": "D",
    "deutschland": "D",
    "d": "D",
    "d<<": "D",
    "deu": "D",
    "utopia": "UTO",
    "uto": "UTO",
    "bangladesh": "BGD",
    "bangladeshi": "BGD",
    "bgd": "BGD",
    "ireland": "IRL",
    "irish": "IRL",
    "eireannach": "IRL",
    "irl": "IRL",
    "greece": "GRC",
    "hellenic": "GRC",
    "ελληνικη": "GRC",
    "grc": "GRC",
    "czech republic": "CZE",
    "ceska republika": "CZE",
    "cze": "CZE",
    "slovak republic": "SVK",
    "slovenska republika": "SVK",
    "slovak": "SVK",
    "svk": "SVK",
    "sk": "SVK",
    "switzerland": "CHE",
    "schweiz": "CHE",
    "suisse": "CHE",
    "svizzera": "CHE",
    "svizra": "CHE",
    "che": "CHE",
    "uganda": "UGA",
    "ugandan": "UGA",
    "uga": "UGA",
}


# Printed sex markings, folded. A heading-specific table applies only when that
# heading wording is printed, never from nationality or a person's name.
SEX_MARKINGS = {
    "m": "M", "male": "M", "masculin": "M", "man": "M", "mannelijk": "M",
    "f": "F", "female": "F", "feminin": "F", "vrouw": "F", "vrouwelijk": "F",
    "x": "X", "ذكر": "M", "انثى": "F",
}
SEX_MARKINGS_BY_HEADING = {"geslacht": {"v": "F"}}


def normalize_sex(value: str, heading: str = "") -> str | None:
    """Resolve a printed sex marking; paired translations must agree."""
    tokens = [part.strip() for part in fold_text(value).split("/")]
    markings = dict(SEX_MARKINGS)
    folded_heading = fold_text(heading)
    for wording, extra in SEX_MARKINGS_BY_HEADING.items():
        # The heading's own wording, or its explicit translated pair, selects the table.
        pair = set(extra) | {key for key, code in SEX_MARKINGS.items()
                             if len(key) == 1 and code in extra.values()}
        if wording in folded_heading or set(tokens) == pair:
            markings.update(extra)
    readings = {markings.get(token) for token in tokens}
    return readings.pop() if len(readings) == 1 and None not in readings else None


def fold_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold().translate(str.maketrans("’‘ʼ", "'''"))
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


def country_code(value: str) -> str:
    return known_country_code(value) or value.strip().upper()


@lru_cache(maxsize=1)
def _country_database() -> dict[str, str | None]:
    """Cache public reference data only, never observed document text."""
    import pycountry

    aliases: dict[str, str | None] = {}
    for country in pycountry.countries:
        code = "D" if country.alpha_3 == "DEU" else country.alpha_3
        for key in ("alpha_2", "alpha_3", "numeric", "name", "official_name", "common_name"):
            value = getattr(country, key, None)
            if value:
                folded = fold_text(value)
                aliases[folded] = code if folded not in aliases or aliases[folded] == code else None
    return aliases


def _exact_country_code(text: str) -> str | None:
    """Resolve explicit country wording/codes locally, without fuzzy matching."""
    if text in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[text]
    for code, name in (ICAO_ISSUERS | ICAO_NATIONALITIES).items():
        if text in {code.casefold(), fold_text(name)}:
            return code
    return _country_database().get(text)


def known_country_code(value: str) -> str | None:
    """Normalize supported aliases only, without inventing a code for unknown text."""
    text = fold_text(value)
    exact = _exact_country_code(text)
    if exact:
        return exact
    if "/" in text:
        segments = [part.strip() for part in text.split("/")]
        codes = [_exact_country_code(part) for part in segments]
        if all(codes) and len(set(codes)) == 1:
            return codes[0]
    # Multilingual wording is equivalent only when every recognized part agrees.
    # Never discard an unknown part or infer nationality from the issuing state.
    aliases = sorted(COUNTRY_ALIASES, key=len, reverse=True)
    parts: list[str] = []
    while text:
        matched = next((alias for alias in aliases
                        if text == alias or text.startswith(alias + " ")
                        or text.startswith(alias + "/")), None)
        if matched is None:
            return None
        parts.append(COUNTRY_ALIASES[matched])
        text = re.sub(r"^[\s/]+", "", text[len(matched):])
    return parts[0] if parts and len(set(parts)) == 1 else None


# ICAO Doc 9303-3, section 5 (including amendments through March 2024).
# https://www.icao.int/sites/default/files/publications/DocSeries/9303_p3_cons_en.pdf
# These identify states/organizations, not a printed passport office.
ICAO_ISSUERS = {
    "D": "Germany", "RKS": "Kosovo", "EUE": "European Union",
    "UNO": "United Nations Organization", "UNA": "United Nations specialized agency",
    "UNK": "United Nations Interim Administration Mission in Kosovo",
    "XBA": "African Development Bank", "XIM": "African Export-Import Bank",
    "XCC": "Caribbean Community", "XCE": "Council of Europe",
    "XCO": "Common Market for Eastern and Southern Africa",
    "XEC": "Economic Community of West African States",
    "XPO": "International Criminal Police Organization",
    "XES": "Organization of Eastern Caribbean States",
    "XMP": "Parliamentary Assembly of the Mediterranean",
    "XOM": "Sovereign Military Order of Malta",
    "XDC": "Southern African Development Community",
    "ANT": "Netherlands Antilles", "NTZ": "Neutral Zone", "UTO": "Utopia",
}
ICAO_NATIONALITIES = {
    "GBD": "British Overseas Territories Citizen", "GBN": "British National (Overseas)",
    "GBO": "British Overseas Citizen", "GBP": "British Protected Person",
    "GBS": "British Subject", "XXA": "Stateless person",
    "XXB": "Refugee (1951 Convention)", "XXC": "Refugee (other)",
    "XXX": "Unspecified nationality",
}


def icao_code_name(value: str, *, nationality: bool = False) -> str | None:
    """Resolve exact ICAO codes; never accept an ISO alpha-2 code or guess a typo."""
    import pycountry

    code = value.strip().upper()
    if code == "D<<":
        code = "D"
    if code in ICAO_ISSUERS:
        return ICAO_ISSUERS[code]
    if nationality and code in ICAO_NATIONALITIES:
        return ICAO_NATIONALITIES[code]
    # Germany's ICAO code is D, not its ISO alpha-3 code DEU.
    country = pycountry.countries.get(alpha_3=code) if re.fullmatch(r"[A-Z]{3}", code) and code != "DEU" else None
    return country.name if country else None
