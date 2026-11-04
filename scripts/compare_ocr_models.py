"""Run once per model pair in a fresh process. Uses only rendered fictional documents."""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import psutil
from generate_fixture import font
from PIL import Image, ImageDraw
from rapidfuzz.distance import Levenshtein

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.store import ScanStore
from app.extractors.field_extractor import extract_fields
from app.schemas.models import ScanOptions
from app.services.ocr import OCRService
from app.services.pipeline import run_scan
from evaluate_accuracy import EXPECTED
from evaluate_accuracy import cases as accuracy_cases


def fixture(fmt, distortion):
    w, h = 1200, 780
    image = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(image)
    labels, polygons = [], []

    def write(x, y, text, mono=False):
        face = font(30 if mono else 28, mono)
        l, t, r, b = draw.textbbox((x, y), text, font=face)
        polygons.append([[l, t], [r, t], [r, b], [l, b]])
        labels.append(text)
        draw.text((x, y), text, fill="black", font=face)

    passport = fmt == "TD3"
    write(
        40, 25, ("PASSPORT" if passport else "IDENTITY CARD") + " - FICTIONAL SPECIMEN"
    )
    expected = {
        "document_number": "L898902C3" if passport else "D23145890",
        "date_of_birth": "1974-08-12",
        "date_of_issue": "2002-04-16",
        "date_of_expiry": "2012-04-15",
        "nationality": "Canadian",
        "issuing_country": "USA",
        "sex": "F",
    }
    if passport:
        write(55, 94, "Surname: ERIKSSON")
        write(560, 94, "Given names: ANNA MARIA")
        expected.update(surname="ERIKSSON", given_names="ANNA MARIA")
    else:
        write(55, 95, "Full name: ANNA MARIA ERIKSSON")
        expected.update(full_name="ANNA MARIA ERIKSSON")
    rows = [
        "Nationality: Canadian",
        "Issuing country: USA",
        ("Passport No: " if passport else "Document number: ")
        + expected["document_number"],
        "Date of birth: " + ("12 AUG 1974" if passport else "12.08.1974"),
        "Date of issue: 16th April 2002",
        "Date of expiry: 15/04/2012",
        "Sex: F",
    ]
    for i, value in enumerate(rows):
        write(55, 155 + 54 * i, value)
    # Adapt public fictional TD examples. Nationality and issuer aren't part of
    # the composite check. The names and number/date/check positions stay intact.
    names = "ERIKSSON<<ANNA<MARIA"
    if fmt == "TD3":
        mrz = [
            "P<USA" + names.ljust(39, "<"),
            "L898902C36CAN7408122F1204159ZE184226B<<<<<10",
        ]
    elif fmt == "TD2":
        mrz = ["I<USA" + names.ljust(31, "<"), "D231458907CAN7408122F1204159<<<<<<<6"]
    else:
        mrz = [
            "I<USAD231458907" + "<" * 15,
            "7408122F1204159CAN" + "<" * 11 + "6",
            names.ljust(30, "<"),
        ]
    if distortion == "damaged-check":
        mrz[1] = mrz[1][:-1] + "7"
    for i, line in enumerate(mrz):
        write(50, 575 + 48 * i, line, True)
    image = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    boxes = np.float32(polygons)
    if distortion == "blur":
        image = cv2.GaussianBlur(image, (7, 7), 1.3)
    elif distortion == "rotated":
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        boxes = np.stack((h - 1 - boxes[:, :, 1], boxes[:, :, 0]), axis=-1)
    elif distortion == "perspective":
        transform = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]]),
            np.float32([[60, 45], [1150, 10], [1190, 740], [22, 765]]),
        )
        image = cv2.warpPerspective(
            image, transform, (w, h), borderValue=(210, 210, 210)
        )
        boxes = cv2.perspectiveTransform(boxes, transform)
    return image, labels, boxes, expected, mrz


def corrected_boxes(boxes, shape, metadata):
    h, w = shape[:2]
    if metadata.crop_applied:
        corners = np.float32(metadata.corners) * [w - 1, h - 1]
        w, h = metadata.width, metadata.height
        if metadata.rotation in (90, 270):
            w, h = h, w
        transform = cv2.getPerspectiveTransform(
            corners.astype("float32"),
            np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]]),
        )
        boxes = cv2.perspectiveTransform(boxes, transform)
    x, y = boxes[:, :, 0], boxes[:, :, 1]
    if metadata.rotation == 90:
        return np.stack((h - 1 - y, x), axis=-1)
    if metadata.rotation == 270:
        return np.stack((y, w - 1 - x), axis=-1)
    if metadata.rotation == 180:
        return np.stack((w - 1 - x, h - 1 - y), axis=-1)
    return boxes


def region_metrics(boxes, labels, lines):
    candidates = []
    for i, box in enumerate(boxes):
        for j, line in enumerate(lines):
            actual = np.float32(line.bounding_box)
            common, _ = cv2.intersectConvexConvex(box, actual)
            union = cv2.contourArea(box) + cv2.contourArea(actual) - common
            if union and common / union >= 0.5:
                candidates.append((common / union, i, j))
    found, used = set(), set()
    chars = edits = 0
    for _, i, j in sorted(candidates, reverse=True):
        if i in found or j in used:
            continue
        found.add(i)
        used.add(j)
        chars += len(labels[i])
        edits += Levenshtein.distance(labels[i], lines[j].text)
    return {
        "hits": len(found),
        "expected_regions": len(labels),
        "predicted_regions": len(lines),
        "matched_characters": chars,
        "character_edits": edits,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small-dir", required=True)
    parser.add_argument("--medium-det")
    parser.add_argument("--medium-rec")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    engine = OCRService(
        ocr_models_dir=args.small_dir,
        medium_det_path=args.medium_det or "",
        medium_rec_path=args.medium_rec or "",
    )
    start = time.perf_counter()
    engine.warmup()
    rapid = engine._get_engine("latin")
    report = {
        "startup_s": round(time.perf_counter() - start, 2),
        "models": [
            stage.session.session._model_path
            for stage in (rapid.text_det, rapid.text_cls, rapid.text_rec)
        ],
        "dictionary": rapid.cfg.Rec.rec_keys_path,
        "cases": [],
    }
    process = psutil.Process()
    store = ScanStore(600, 1, 100 * 1024**2)
    for fmt, distortion in [
        ("TD3", "clear"),
        ("TD3", "blur"),
        ("TD3", "rotated"),
        ("TD1", "clear"),
        ("TD2", "perspective"),
        ("TD3", "damaged-check"),
    ]:
        image, labels, boxes, expected, mrz = fixture(fmt, distortion)
        job = store.create("synthetic")
        encoded = cv2.imencode(".png", image)[1].tobytes()
        start = time.perf_counter()
        run_scan(job, {"front": encoded}, ScanOptions(date_order="dmy"), store, engine)
        elapsed = time.perf_counter() - start
        if job.result is None:
            raise RuntimeError(job.error or job.status)
        result = job.result
        actual = {k: f.value for k, f in result.fields.items()}
        expected["document_type"] = "passport" if fmt == "TD3" else "identity_card"
        actual["document_type"] = result.document_type
        matches = {k: actual.get(k) == v for k, v in expected.items()}
        metrics = region_metrics(
            corrected_boxes(boxes, image.shape, result.images[0]),
            labels,
            result.ocr_lines,
        )
        item = dict(
            format=fmt,
            variant=distortion,
            seconds=round(elapsed, 2),
            matches=matches,
            mrz_exact=result.mrz.raw_lines == mrz,
            checksum=result.mrz.checksum_valid,
            expected_checksum=distortion != "damaged-check",
            **metrics,
        )
        report["cases"].append(item)
        print(
            fmt,
            distortion,
            sum(matches.values()),
            "/",
            len(matches),
            round(elapsed, 2),
            "s",
            flush=True,
        )
        store.delete(job.scan_id, "synthetic")
    report["tilted_regressions"] = []
    for name, image in accuracy_cases().items():
        if not name.startswith("distant_blur_tilt_"):
            continue
        # Repeat the existing real-OCR regression at its actual entry point.
        lines = engine.read(image)
        fields = extract_fields(lines, date_order="dmy")["fields"]
        missed = {key: fields[key].value if key in fields else None for key, value in EXPECTED.items()
                  if key not in fields or fields[key].value != value}
        report["tilted_regressions"].append({"case": name, "exact": len(EXPECTED)-len(missed),
                                             "total": len(EXPECTED), "missed": missed})
    memory = process.memory_info()
    report["peak_working_set_mib"] = (
        round(memory.peak_wset / 1024**2, 1) if hasattr(memory, "peak_wset") else None
    )
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
