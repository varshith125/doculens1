"""Functional tests against a running DocuLens server, using only fictional documents.

    python scripts/functional_tests.py --base http://127.0.0.1:8000

Each check exercises the HTTP API the way the website does. Exit code 0 means
every check passed.
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPECIMEN = ROOT / "docs" / "specimen.png"  # ICAO 9303 fictional specimen
EXPECTED = {"surname": "ERIKSSON", "given_names": "ANNA MARIA", "document_number": "L898902C3"}


def png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class Session:
    def __init__(self, base: str):
        self.base = base.rstrip("/") + "/api/v1"
        self.client = httpx.Client(timeout=180)

    def start(self) -> int:
        return self.client.post(self.base + "/session").status_code

    def upload(self, data: bytes, name: str = "doc.png", options: str = "{}", back: bytes | None = None):
        files = {"front": (name, data)}
        if back:
            files["back"] = ("back.png", back)
        return self.client.post(self.base + "/scans", files=files, data={"options": options})

    def scan(self, data: bytes, **kwargs) -> tuple[dict | None, int]:
        response = self.upload(data, **kwargs)
        if response.status_code != 202:
            return None, response.status_code
        scan_id = response.json()["scan_id"]
        while True:
            body = self.client.get(f"{self.base}/scans/{scan_id}").json()
            if body["status"] in {"completed", "failed"}:
                body["scan_id"] = scan_id
                return body, 202
            time.sleep(0.25)


def run(base: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        results.append((name, bool(passed), detail))

    user = Session(base)
    health = user.client.get(user.base + "/health").json()
    check("Health check reports the OCR engine ready", health.get("ocr_ready") is True, json.dumps(health))
    check("Website home page loads", user.client.get(base.rstrip("/") + "/").status_code == 200)
    check("Scanning without a session is refused (401)",
          httpx.post(user.base + "/scans", files={"front": ("a.png", b"x")}).status_code == 401)
    check("A browser session can be created", user.start() == 200)

    specimen = SPECIMEN.read_bytes()
    started = time.perf_counter()
    body, _ = user.scan(specimen)
    fields = body["result"]["fields"]
    check("Specimen passport scans successfully", body["status"] == "completed",
          f"{time.perf_counter() - started:.1f} s")
    check("Name and passport number are correct",
          all(fields[key]["value"] == value for key, value in EXPECTED.items()))
    check("Dates are correct",
          (fields["date_of_birth"]["value"], fields["date_of_expiry"]["value"]) == ("1974-08-12", "2012-04-15"))
    check("MRZ check digits pass", body["result"]["mrz"]["checksum_valid"] is True)
    check("Corrected preview arrives with the result",
          any(p["variant"] == "corrected" for p in body["previews"]))
    check("Scan is deleted as soon as its result is delivered",
          user.client.get(f"{user.base}/scans/{body['scan_id']}").status_code == 404)

    for angle in (90, 180, 270):
        rotated = png(Image.open(SPECIMEN).rotate(angle, expand=True))
        body, _ = user.scan(rotated)
        check(f"Document rotated {angle} degrees is read correctly",
              body["result"]["fields"]["document_number"]["value"] == EXPECTED["document_number"],
              f"detected rotation {body['result']['images'][0]['rotation']}")

    pdf = io.BytesIO()
    Image.open(SPECIMEN).convert("RGB").save(pdf, "PDF")
    body, _ = user.scan(pdf.getvalue(), name="doc.pdf")
    check("Single-page PDF is read correctly",
          body["status"] == "completed"
          and body["result"]["fields"]["document_number"]["value"] == EXPECTED["document_number"])
    body, _ = user.scan(specimen, back=specimen)
    check("Front and back can be uploaded together",
          body["status"] == "completed" and len(body["result"]["images"]) == 2)

    check("A non-image file is refused (415)", user.upload(b"hello world", name="x.txt").status_code == 415)
    check("An oversized file is refused (413)",
          user.upload(b"\x89PNG\r\n\x1a\n" + b"0" * (13 * 1024 * 1024)).status_code == 413)
    check("Invalid scan options are refused (422)",
          user.upload(specimen, options='{"language": "klingon"}').status_code == 422)
    body, _ = user.scan(png(Image.new("RGB", (20, 20), "white")))
    check("A too-small image fails with a clear message",
          body["status"] == "failed" and "small" in (body["error"] or ""), body["error"] or "")
    body, _ = user.scan(png(Image.new("RGB", (800, 600), "white")))
    check("A blank page completes with a warning instead of crashing",
          body["status"] == "completed" and any("No readable" in w for w in body["result"]["warnings"]))

    response = user.client.post(user.base + "/extract", files={"file": ("doc.png", specimen)},
                                data={"options": "{}"})
    check("One-shot /extract endpoint returns the fields",
          response.status_code == 200
          and response.json()["fields"]["document_number"]["value"] == EXPECTED["document_number"])

    scan_id = user.upload(specimen).json()["scan_id"]
    time.sleep(0.3)
    cancelled = user.client.delete(f"{user.base}/scans/{scan_id}").status_code
    check("A running scan can be cancelled",
          cancelled == 204 and user.client.get(f"{user.base}/scans/{scan_id}").status_code == 404)

    other = Session(base)
    other.start()
    scan_id = user.upload(specimen).json()["scan_id"]
    check("Another user cannot see someone else's scan (404)",
          other.client.get(f"{other.base}/scans/{scan_id}").status_code == 404)
    user.client.delete(f"{user.base}/scans/{scan_id}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    results = run(args.base)
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} functional checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
