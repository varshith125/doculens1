"""Compare extracted fields on repeatable fictional clear/blurred document images."""

import argparse
import inspect
import json
import time
from pathlib import Path

import cv2
import numpy as np
from app.extractors.field_extractor import extract_fields
from app.services.ocr import OCRService

EXPECTED = {
    "surname": "EXAMPLE",
    "given_names": "TEST PERSON",
    "document_number": "A1234567",
    "date_of_birth": "1990-04-03",
    "date_of_issue": "2020-06-15",
    "date_of_expiry": "2030-06-14",
}


def cases():
    image = np.full((600, 960, 3), 247, np.uint8)
    rows = [
        (45, 55, "PASSPORT - FICTIONAL TEST ONLY", 0.9),
        (45, 125, "SURNAME / NOM", 0.62),
        (45, 160, "EXAMPLE", 0.85),
        (440, 125, "GIVEN NAMES", 0.62),
        (440, 160, "TEST PERSON", 0.85),
        (45, 245, "PASSPORT NO. A1234567", 0.72),
        (45, 325, "D.O.B. 03 / 04 / 1990", 0.72),
        (45, 405, "DATE OF ISSUE: 15-06-2020", 0.72),
        (45, 485, "DATE OF EXPIRY: 14.06.2030", 0.72),
    ]
    for x, y, text, scale in rows:
        cv2.putText(
            image,
            text,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
    variants = {
        "clear": image,
        "mild_blur_sigma_0_8": cv2.GaussianBlur(image, (5, 5), 0.8),
        "blur_sigma_1_2": cv2.GaussianBlur(image, (7, 7), 1.2),
        "low_resolution": cv2.resize(image, (576, 360), interpolation=cv2.INTER_AREA),
    }
    for scale, angle in ((0.45, 15), (0.4, 11), (0.5, 18)):
        blurred = cv2.GaussianBlur(image, (5, 5), 0.9)
        tilted = cv2.warpAffine(
            blurred,
            cv2.getRotationMatrix2D((480, 300), angle, 1),
            (960, 600),
            borderValue=(247, 247, 247),
        )
        variants[f"distant_blur_tilt_{angle}"] = cv2.resize(
            tilted, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )
    return variants


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    service = OCRService()
    service.warmup()
    results = []
    for name, image in cases().items():
        started = time.perf_counter()
        lines = service.read(image)
        if "date_order" in inspect.signature(extract_fields).parameters:
            extraction = extract_fields(lines, date_order="dmy")
        else:
            extraction = extract_fields(lines)
        fields = {key: value.value for key, value in extraction["fields"].items()}
        matches = {key: fields.get(key) == value for key, value in EXPECTED.items()}
        item = {
            "case": name,
            "correct": sum(matches.values()),
            "total": len(matches),
            "matches": matches,
            "fields": fields,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "ocr_lines": [line.model_dump() for line in lines],
        }
        results.append(item)
        print(
            f"{name}: {item['correct']}/{item['total']} exact fields, {item['elapsed_ms']} ms",
            flush=True,
        )
    args.output.write_text(
        json.dumps(
            {
                "fixture": "Fictional synthetic document; DMY printed dates",
                "expected": EXPECTED,
                "cases": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
