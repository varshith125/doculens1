"""Generate synthetic specimen passports with known answers, then score DocuLens on them.

Every person, number and authority is invented, and every page carries a
SPECIMEN watermark. Layouts follow the shared ICAO 9303 field set, but no real
country's design is reproduced. Usage:

    python scripts/synthetic_passports.py generate --count 24
    python scripts/synthetic_passports.py evaluate
    python scripts/synthetic_passports.py evaluate --variants clean,rot180,blur

Output goes to synthetic-passports/ (ignored by git).
"""

import argparse
import io
import json
import math
import random
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "synthetic-passports"
FONTS = Path("C:/Windows/Fonts")

SURNAMES = ["Müller", "García López", "O'Connor", "Van der Berg", "Rossi", "Silva Santos",
            "Dubois", "Nowak", "Haddad", "Kumar", "Lindqvist", "Ferreira", "Costa", "Novák",
            "Petersen", "Moreau", "Schmidt", "Kowalski", "Jensen", "Romero"]
GIVEN = ["Anna Maria", "José", "Liam", "Sofia", "Élodie", "Mateo", "Priya", "Lars Erik",
         "Chloé", "Noah", "Isabel", "Tomás", "Ingrid", "Arjun", "Lucía", "Hugo", "Emma Louise",
         "Pieter", "Zofia", "Marco"]
PLACES = ["Avalon", "Brightwater", "Eastport", "Northfield", "Riverton", "Lakeside",
          "Westbury", "Greenhill", "Stonebridge", "Fairhaven"]
# (ICAO code, printed nationality, country title, MRZ code). Invented authorities only.
COUNTRIES = [
    ("UTO", "Utopian", "REPUBLIC OF UTOPIA", "UTO"),
    ("FRA", "Française", "RÉPUBLIQUE FRANÇAISE", "FRA"),
    ("NLD", "Nederlandse", "KONINKRIJK DER NEDERLANDEN", "NLD"),
    ("D", "Deutsch", "BUNDESREPUBLIK DEUTSCHLAND", "D<<"),
    ("IND", "Indian", "REPUBLIC OF INDIA", "IND"),
    ("CAN", "Canadian", "CANADA", "CAN"),
    ("IRL", "Irish", "IRELAND", "IRL"),
    ("GBR", "British Citizen", "UNITED KINGDOM", "GBR"),
    ("ESP", "Española", "REINO DE ESPAÑA", "ESP"),
    ("ITA", "Italiana", "REPUBBLICA ITALIANA", "ITA"),
]
AUTHORITIES = ["Specimen Office", "Passport Bureau Avalon", "Civic Registry North",
               "Ministry of Specimens", "Office of Travel Documents"]
# Caption wording per language. Written here independently of the app's alias table.
CAPTIONS = {
    "en": {"type": "Type", "code": "Code", "number": "Passport No.", "surname": "Surname",
           "given": "Given names", "nationality": "Nationality", "dob": "Date of birth",
           "sex": "Sex", "pob": "Place of birth", "doi": "Date of issue",
           "doe": "Date of expiry", "authority": "Authority"},
    "fr": {"type": "Type", "code": "Code", "number": "N° du passeport", "surname": "Nom",
           "given": "Prénoms", "nationality": "Nationalité", "dob": "Date de naissance",
           "sex": "Sexe", "pob": "Lieu de naissance", "doi": "Date de délivrance",
           "doe": "Date d'expiration", "authority": "Autorité"},
    "es": {"type": "Tipo", "code": "Código", "number": "N.º de pasaporte", "surname": "Apellidos",
           "given": "Nombres", "nationality": "Nacionalidad", "dob": "Fecha de nacimiento",
           "sex": "Sexo", "pob": "Lugar de nacimiento", "doi": "Fecha de expedición",
           "doe": "Fecha de caducidad", "authority": "Autoridad"},
    "de": {"type": "Typ", "code": "Kode", "number": "Pass-Nr.", "surname": "Name",
           "given": "Vornamen", "nationality": "Staatsangehörigkeit", "dob": "Geburtsdatum",
           "sex": "Geschlecht", "pob": "Geburtsort", "doi": "Ausstellungsdatum",
           "doe": "Gültig bis", "authority": "Behörde"},
    "nl": {"type": "Type", "code": "Code", "number": "Documentnummer", "surname": "Naam",
           "given": "Voornamen", "nationality": "Nationaliteit", "dob": "Geboortedatum",
           "sex": "Geslacht", "pob": "Geboorteplaats", "doi": "Datum van afgifte",
           "doe": "Geldig tot", "authority": "Instantie"},
}
NUMBERING = {"surname": 1, "given": 2, "nationality": 3, "dob": 4, "sex": 5, "pob": 6,
             "doi": 7, "doe": 8, "authority": 9}
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
LOCAL_MONTHS = {"fr": ["JAN", "FÉV", "MARS", "AVR", "MAI", "JUIN", "JUIL", "AOÛT", "SEPT", "OCT", "NOV", "DÉC"],
                "es": ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"],
                "de": ["JAN", "FEB", "MÄR", "APR", "MAI", "JUN", "JUL", "AUG", "SEP", "OKT", "NOV", "DEZ"],
                "nl": ["JAN", "FEB", "MAA", "APR", "MEI", "JUN", "JUL", "AUG", "SEP", "OKT", "NOV", "DEC"]}
VARIANTS = ["clean", "rot90", "rot180", "rot270", "tilt", "blur", "lowres", "jpeg", "desk"]


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def check_digit(value):
    weights = (7, 3, 1)
    total = 0
    for i, ch in enumerate(value):
        n = int(ch) if ch.isdigit() else (ord(ch) - 55 if ch.isalpha() else 0)
        total += n * weights[i % 3]
    return str(total % 10)


def mrz_name(text):
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).upper()
    plain = plain.replace("'", "").replace("-", " ")
    return "<".join(plain.split())


def mrz_lines(p):
    names = f"{mrz_name(p['surname'])}<<{mrz_name(p['given_names'])}"
    first = f"P<{p['mrz_code']}{names}"[:44].ljust(44, "<")
    number = p["document_number"].ljust(9, "<")
    dob = p["date_of_birth"].replace("-", "")[2:]
    doe = p["date_of_expiry"].replace("-", "")[2:]
    second = (number + check_digit(number) + p["mrz_code"] + dob + check_digit(dob) + p["sex"]
              + doe + check_digit(doe) + "<" * 14 + "<")
    second += check_digit(second[:10] + second[13:20] + second[21:43])
    return first, second


def printed_date(iso, style, lang):
    d = date.fromisoformat(iso)
    if style == "dmy_text":
        return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}"
    if style == "bilingual" and lang in LOCAL_MONTHS:
        local = LOCAL_MONTHS[lang][d.month - 1]
        month = MONTHS[d.month - 1]
        return f"{d.day:02d} {local}/{month} {d.year}" if local != month else f"{d.day:02d} {month} {d.year}"
    if style == "dots":
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def person(rng):
    code, nationality, title, mrz_code = rng.choice(COUNTRIES)
    dob = date(1950, 1, 1) + timedelta(days=rng.randrange(0, 365 * 55))
    doi = date(2016, 1, 1) + timedelta(days=rng.randrange(0, 365 * 9))
    doe = doi.replace(year=doi.year + 10) - timedelta(days=1)
    letters = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(2))
    return {
        "surname": rng.choice(SURNAMES), "given_names": rng.choice(GIVEN),
        "document_number": letters + "".join(rng.choice("0123456789") for _ in range(7)),
        "nationality_code": code, "nationality": nationality, "title": title, "mrz_code": mrz_code,
        "issuing_country_code": code,
        "date_of_birth": dob.isoformat(), "date_of_issue": doi.isoformat(),
        "date_of_expiry": doe.isoformat(), "sex": rng.choice("MF"),
        "place_of_birth": rng.choice(PLACES), "issuing_authority": rng.choice(AUTHORITIES),
        "document_code": "P",
    }


def background(rng, size):
    w, h = size
    base = np.array([rng.randint(225, 248), rng.randint(225, 248), rng.randint(225, 248)], float)
    tint = np.array([rng.randint(200, 240), rng.randint(215, 245), rng.randint(225, 250)], float)
    t = np.linspace(0, 1, w)[None, :, None]
    img = base * (1 - t) + tint * t
    img = np.repeat(img, h, axis=0)
    canvas = Image.fromarray(img.astype(np.uint8))
    draw = ImageDraw.Draw(canvas)
    colour = tuple(int(c) for c in (tint * 0.85))
    for k in range(rng.randint(18, 30)):  # guilloche-like waves
        amp, freq, phase, y0 = rng.uniform(8, 40), rng.uniform(0.004, 0.02), rng.uniform(0, 6.3), rng.uniform(0, h)
        points = [(x, y0 + amp * math.sin(freq * x + phase) + 15 * math.sin(0.003 * x * (k + 1))) for x in range(0, w, 6)]
        draw.line(points, fill=colour, width=1)
    noise = np.asarray(canvas, np.int16) + np.random.default_rng(rng.randrange(1 << 30)).integers(-6, 7, (h, w, 3))
    return Image.fromarray(np.clip(noise, 0, 255).astype(np.uint8))


def caption(field, langs, numbered):
    text = " / ".join(dict.fromkeys(CAPTIONS[lang][field] for lang in langs))
    if numbered and field in NUMBERING:
        text = f"{NUMBERING[field]}. {text}"
    return text


def render(p, rng):
    w, h = 1250, 880
    page = background(rng, (w, h))
    draw = ImageDraw.Draw(page)
    local = {"FRA": "fr", "ESP": "es", "D": "de", "NLD": "nl"}.get(p["nationality_code"], "en")
    langs = rng.choice([["en"], ["en", "fr"], [local, "en"] if local != "en" else ["en", "fr"],
                        [local, "en", "fr"] if local not in ("en", "fr") else ["en", "fr"]])
    numbered = rng.random() < 0.4
    layout = rng.choice(["stacked", "stacked", "inline", "two_column"])
    columns_top = layout != "inline" and rng.random() < 0.6
    date_style = rng.choice(["dmy_text", "bilingual", "dots", "slashes"])
    value_font_name = rng.choice(["arialbd.ttf", "verdanab.ttf", "tahomabd.ttf", "calibrib.ttf", "segoeuib.ttf"])
    cap_font_name = rng.choice(["arial.ttf", "verdana.ttf", "tahoma.ttf", "calibri.ttf", "segoeui.ttf"])
    value_size = rng.randint(26, 32)
    cap_font, val_font = font(cap_font_name, rng.randint(13, 16)), font(value_font_name, value_size)
    ink, cap_ink = (20, 20, 30), rng.choice([(40, 60, 140), (70, 70, 90), (120, 40, 60)])

    draw.text((40, 28), p["title"], font=font("arialbd.ttf", 40), fill=(60, 60, 110))
    draw.text((40, 80), " / ".join(dict.fromkeys(["PASSPORT", "PASSEPORT"] + (["PASAPORTE"] if local == "es" else []))),
              font=font("arial.ttf", 18), fill=cap_ink)
    draw.rectangle((40, 160, 320, 520), fill=(205, 205, 210), outline=(150, 150, 160))
    draw.ellipse((115, 210, 245, 360), fill=(175, 170, 170))
    draw.ellipse((80, 360, 280, 520), fill=(175, 170, 170))

    dates = {k: printed_date(p[f"date_of_{k}"], date_style, local) for k in ("birth", "issue", "expiry")}
    values = {"type": "P", "code": p["issuing_country_code"], "number": p["document_number"],
              "surname": p["surname"], "given": p["given_names"], "nationality": p["nationality"],
              "dob": dates["birth"], "sex": p["sex"] if local != "nl" else ("V/F" if p["sex"] == "F" else "M/M"),
              "pob": p["place_of_birth"], "doi": dates["issue"], "doe": dates["expiry"],
              "authority": p["issuing_authority"]}
    x0, y = 360, 150
    step = value_size + 30

    def block(field, x, y):
        draw.text((x, y), caption(field, langs, numbered), font=cap_font, fill=cap_ink)
        draw.text((x + 2, y + 18), values[field], font=val_font, fill=ink)

    if columns_top:
        for field, dx in (("type", 0), ("code", 90), ("number", 560)):
            block(field, x0 + dx, y)
        y += step
    order = [f for f in ("surname", "given", "nationality", "dob", "sex", "pob", "doi", "doe", "authority")]
    if not columns_top:
        order = ["number"] + order
    if layout == "inline":
        for field in order:
            draw.text((x0, y), f"{caption(field, langs, numbered)}: {values[field]}", font=val_font, fill=ink)
            y += value_size + 22
    elif layout == "two_column":
        left = [f for f in order if f in ("number", "surname", "given", "nationality", "pob")]
        right = [f for f in order if f not in left]
        for i, field in enumerate(left):
            block(field, x0, y + i * step)
        for i, field in enumerate(right):
            block(field, x0 + 470, y + i * step)
    else:
        for field in order:
            block(field, x0, y)
            y += step
    mrz_font = font("consola.ttf", 37)
    first, second = mrz_lines(p)
    draw.text((40, 770), first, font=mrz_font, fill=ink)
    draw.text((40, 818), second, font=mrz_font, fill=ink)

    mark = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mark).text((260, 340), "SPECIMEN", font=font("arialbd.ttf", 150), fill=70)
    mark = mark.rotate(18, center=(w / 2, h / 2))
    page.paste(Image.new("RGB", (w, h), (255, 255, 255)), (0, 0), mark)
    style = {"languages": langs, "numbered": numbered, "layout": layout, "columns_top": columns_top,
             "date_style": date_style, "font": value_font_name}
    return page, style


def distort(page, variant, rng):
    if variant == "rot90":
        return page.rotate(-90, expand=True)
    if variant == "rot180":
        return page.rotate(180)
    if variant == "rot270":
        return page.rotate(90, expand=True)
    if variant == "tilt":
        return page.rotate(rng.choice([-1, 1]) * rng.uniform(5, 9), expand=True, fillcolor=(255, 255, 255),
                           resample=Image.Resampling.BICUBIC)
    if variant == "blur":
        return page.filter(ImageFilter.GaussianBlur(1.6))
    if variant == "lowres":
        return page.resize((page.width // 2, page.height // 2), Image.Resampling.LANCZOS)
    if variant == "desk":
        desk = Image.new("RGB", (page.width + 400, page.height + 300), (92, 72, 58))
        tilted = page.rotate(rng.uniform(-6, 6), expand=True, fillcolor=(92, 72, 58), resample=Image.Resampling.BICUBIC)
        desk.paste(tilted, (200 - (tilted.width - page.width) // 2, 150 - (tilted.height - page.height) // 2))
        return desk
    return page


def encode(image, variant):
    buffer = io.BytesIO()
    quality = 45 if variant == "jpeg" else 92
    image.save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def generate(count, seed):
    OUT.mkdir(exist_ok=True)
    rng = random.Random(seed)
    answers = []
    for i in range(count):
        p = person(rng)
        page, style = render(p, rng)
        name = f"specimen-{i:03d}"
        page.save(OUT / f"{name}.png")
        answers.append({"id": name, "style": style, "expected": {k: p[k] for k in (
            "surname", "given_names", "document_number", "nationality_code", "date_of_birth",
            "sex", "place_of_birth", "date_of_issue", "date_of_expiry", "issuing_authority",
            "issuing_country_code", "document_code")}})
    (OUT / "answers.json").write_text(json.dumps(answers, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {count} specimens in {OUT}")


def fold(text):
    text = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).replace("'", "").split())


def actual_values(result):
    from app.patterns.common import known_country_code

    fields = {**{f.field_name: f for f in result.other_fields}, **result.fields}

    def value(name):
        field = fields.get(name)
        return (field.normalized_value or field.value) if field else None

    nationality = fields.get("nationality")
    code = None
    if nationality and nationality.value:
        code = nationality.code or known_country_code(nationality.value) or nationality.value
    issuer = fields.get("country_code") or fields.get("issuing_country")
    issuer_code = (issuer.code or known_country_code(issuer.value or "") or issuer.value) if issuer else None
    return {"surname": value("surname"), "given_names": value("given_names"),
            "document_number": value("document_number"), "nationality_code": code,
            "date_of_birth": value("date_of_birth"), "sex": value("sex"),
            "place_of_birth": value("place_of_birth"), "date_of_issue": value("date_of_issue"),
            "date_of_expiry": value("date_of_expiry"), "issuing_authority": value("issuing_authority"),
            "issuing_country_code": issuer_code, "document_code": value("document_code")}


def same(field, expected, actual):
    if actual is None:
        return False
    if field in ("document_number", "nationality_code", "issuing_country_code", "sex", "document_code"):
        return str(actual).replace(" ", "").upper().rstrip("<") == str(expected).upper()
    return fold(actual) == fold(expected)


def evaluate(variants, limit):
    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.config import Settings
    from app.core.store import ScanStore
    from app.schemas.models import ScanOptions
    from app.services.ocr import OCRService
    from app.services.pipeline import run_scan

    answers = json.loads((OUT / "answers.json").read_text(encoding="utf-8"))[:limit]
    engine = OCRService()
    engine.warmup()
    rows = []
    for variant in variants:
        rng = random.Random(f"{variant}-distort")
        for item in answers:
            image = distort(Image.open(OUT / f"{item['id']}.png").convert("RGB"), variant, rng)
            store = ScanStore(3600, 1, 160 * 1024 * 1024)
            job = store.create("synthetic")
            started = time.perf_counter()
            run_scan(job, {"front": encode(image, variant)}, ScanOptions(date_order="dmy"), store, engine, Settings())
            seconds = time.perf_counter() - started
            got = actual_values(job.result) if job.result else {}
            checks = {f: same(f, e, got.get(f)) for f, e in item["expected"].items()}
            rows.append({"id": item["id"], "variant": variant, "seconds": round(seconds, 2),
                         "style": item["style"], "checks": checks,
                         "wrong": {f: [item["expected"][f], got.get(f)] for f, ok in checks.items() if not ok}})
            store.clear()
            print(f"{variant:7s} {item['id']} {sum(checks.values())}/{len(checks)} {seconds:.1f}s", flush=True)
    (OUT / "report.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    summarize(rows)


def summarize(rows):
    total = sum(len(r["checks"]) for r in rows)
    correct = sum(sum(r["checks"].values()) for r in rows)
    print(f"\nOVERALL {correct}/{total} fields = {100 * correct / total:.1f}%  "
          f"mean {sum(r['seconds'] for r in rows) / len(rows):.1f}s per scan")
    groups = {"variant": lambda r: r["variant"], "layout": lambda r: r["style"]["layout"],
              "columns_top": lambda r: str(r["style"]["columns_top"]),
              "languages": lambda r: "+".join(r["style"]["languages"]),
              "date_style": lambda r: r["style"]["date_style"]}
    for title, key in groups.items():
        agg = defaultdict(lambda: [0, 0])
        for r in rows:
            agg[key(r)][0] += sum(r["checks"].values())
            agg[key(r)][1] += len(r["checks"])
        print(f"  by {title}: " + ", ".join(f"{k} {100 * a / b:.0f}%" for k, (a, b) in sorted(agg.items())))
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        for f, ok in r["checks"].items():
            agg[f][0] += ok
            agg[f][1] += 1
    print("  by field: " + ", ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(agg.items(), key=lambda x: x[1][0] / x[1][1])))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--count", type=int, default=24)
    g.add_argument("--seed", type=int, default=9303)
    e = sub.add_parser("evaluate")
    e.add_argument("--variants", default="clean")
    e.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args()
    if args.command == "generate":
        generate(args.count, args.seed)
    else:
        variants = [v for v in args.variants.split(",") if v]
        unknown = set(variants) - set(VARIANTS)
        if unknown:
            parser.error(f"unknown variants: {', '.join(sorted(unknown))}; choose from {', '.join(VARIANTS)}")
        evaluate(variants, args.limit)


if __name__ == "__main__":
    main()
