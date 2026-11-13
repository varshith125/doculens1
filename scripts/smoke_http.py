"""Exercise the running HTTP server using only a fictional generated image."""

import argparse
import base64
import io
import time

import httpx
from generate_fixture import specimen_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    output = io.BytesIO()
    specimen_image().save(output, "PNG")
    with httpx.Client(base_url=args.base, timeout=30) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/v1/health").json()["ocr_ready"]
        assert client.post("/api/v1/session").status_code == 200
        response = client.post(
            "/api/v1/scans",
            files={"front": ("fictional.png", output.getvalue(), "image/png")},
        )
        response.raise_for_status()
        scan_id = response.json()["scan_id"]
        with httpx.Client(base_url=args.base) as outsider:
            outsider.post("/api/v1/session")
            assert outsider.get(f"/api/v1/scans/{scan_id}").status_code == 404
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            body = client.get(f"/api/v1/scans/{scan_id}").json()
            if body["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert body["status"] == "completed", body.get("error")
        result = body["result"]
        assert result["fields"]["surname"]["value"] == "ERIKSSON"
        assert result["ocr_lines"]
        corrected = next(p for p in body["previews"] if p["variant"] == "corrected")
        assert base64.b64decode(corrected["jpeg_base64"]).startswith(b"\xff\xd8")
        assert client.get(f"/api/v1/scans/{scan_id}").status_code == 404
        print(
            f"HTTP smoke passed: real OCR, {len(result['fields'])} fields, ownership enforced, "
            "and the scan was deleted as soon as its result was delivered."
        )


if __name__ == "__main__":
    main()
