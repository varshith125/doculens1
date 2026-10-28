"""Generate an explicitly fictional document for OCR regression and benchmarks."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def font(size: int, mono: bool = False):
    candidates = (
        [
            "C:/Windows/Fonts/consola.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
        if mono
        else [
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def specimen_image() -> Image.Image:
    image = Image.new("RGB", (1400, 940), "#dddcd8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 1330, 870), fill="#faf8ee", outline="#74716a", width=3)
    draw.text(
        (115, 105), "PASSPORT  /  SPECIMEN - NOT VALID", font=font(37), fill="#24483e"
    )
    draw.rectangle((115, 200, 380, 580), fill="#e1e2da", outline="#989c90", width=2)
    draw.text((145, 340), "NO PORTRAIT", font=font(27), fill="#5a625a")
    rows = [
        (200, "Surname: ERIKSSON"),
        (270, "Given names: ANNA MARIA"),
        (340, "Passport No: L898902C3"),
        (410, "Nationality: UTO"),
        (480, "Date of birth: 12 AUG 1974"),
        (550, "Date of expiry: 15 APR 2012"),
        (620, "Sex: F"),
    ]
    for y, text in rows:
        draw.text((440, y), text, font=font(31), fill="#181d19")
    # Public ICAO fictional test data; never an actual person's document.
    lines = [
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
    ]
    lines[0] = lines[0].ljust(44, "<")
    for y, line in zip((730, 790), lines, strict=True):
        draw.text((110, y), line, font=font(42, True), fill="#141414")
    return image


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    specimen_image().save(args.output)
    print(f"Created fictional test fixture: {args.output}")
