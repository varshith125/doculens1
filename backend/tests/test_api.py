import io
import tempfile
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.main import create_app
from app.schemas.models import OCRLine
from app.services.ocr import OCRUnavailableError


class TestOCR:
    __test__ = False
    ready = True
    languages = ["latin"]
    fail = False
    gate: threading.Event | None = None

    def warmup(self):
        pass

    def read_oriented(self, image, **_kwargs):
        if self.gate:
            self.gate.wait(timeout=3)
        if self.fail:
            raise OCRUnavailableError("OCR could not read this image.")
        return (
            image,
            [
                OCRLine(
                    text="Surname: SPECIMEN",
                    confidence=0.98,
                    bounding_box=[[30, 30], [300, 30], [300, 60], [30, 60]],
                )
            ],
            0,
        )


@pytest.fixture
def engine():
    return TestOCR()


@pytest.fixture
def client(engine):
    settings = Settings(max_upload_mb=1, allowed_origins=["http://testserver"])
    with TestClient(create_app(settings, engine)) as client:
        client.post("/api/v1/session")
        yield client


def png():
    output = io.BytesIO()
    Image.new("RGB", (800, 500), "white").save(output, "PNG")
    return output.getvalue()


def start(client, image_data=None, **kwargs):
    return client.post(
        "/api/v1/scans", files={"front": ("sample.png", image_data or png(), "image/png")}, **kwargs
    )


def wait_result(client, scan_id):
    for _ in range(200):
        body = client.get(f"/api/v1/scans/{scan_id}").json()
        if body["status"] in {"completed", "failed"}:
            return body
        time.sleep(0.01)
    pytest.fail("Scan did not complete")


def test_upload_result_images_and_delete(client):
    response = start(client)
    assert response.status_code == 202
    scan_id = response.json()["scan_id"]
    result = wait_result(client, scan_id)
    assert result["status"] == "completed", result
    assert result["result"]["fields"]["surname"]["value"] == "SPECIMEN"
    assert result["result"]["ocr_lines"][0]["text"] == "Surname: SPECIMEN"
    image = client.get(f"/api/v1/scans/{scan_id}/image")
    assert image.status_code == 200
    assert image.headers["cache-control"] == "no-store"
    assert image.content.startswith(b"\xff\xd8")
    assert client.delete(f"/api/v1/scans/{scan_id}").status_code == 204
    assert client.get(f"/api/v1/scans/{scan_id}/image").status_code == 404


def test_front_back_upload(client):
    response = client.post(
        "/api/v1/scans",
        files={
            "front": ("front.png", png(), "image/png"),
            "back": ("back.png", png(), "image/png"),
        },
    )
    body = wait_result(client, response.json()["scan_id"])
    assert body["status"] == "completed"
    assert [image["side"] for image in body["result"]["images"]] == ["front", "back"]


@pytest.mark.parametrize(
    "options,expected",
    [
        ("{}", "1990-04-03"),
        ('{"date_order":"mdy"}', "1990-03-04"),
        ('{"date_order":"auto"}', None),
    ],
)
def test_date_order_reaches_extractor(client, engine, monkeypatch, options, expected):
    def read_date(image, **kwargs):
        return (
            image,
            [
                OCRLine(
                    text="D.O.B. 03/04/1990",
                    confidence=0.99,
                    bounding_box=[[30, 30], [300, 30], [300, 60], [30, 60]],
                )
            ],
            0,
        )

    monkeypatch.setattr(engine, "read_oriented", read_date)
    response = start(client, data={"options": options})
    assert response.status_code == 202
    body = wait_result(client, response.json()["scan_id"])
    field = body["result"]["fields"]["date_of_birth"]
    assert field["value"] == field["normalized_value"] == expected
    assert field["raw"] == "03/04/1990"
    if expected is None:
        assert field["display_value"] is None
        assert field["status"] == "uncertain"
        assert field["validation"]["date_order_ambiguous"] is True


def test_requires_session_and_restricts_ownership(client):
    scan_id = start(client).json()["scan_id"]
    client.cookies.clear()
    assert client.get(f"/api/v1/scans/{scan_id}").status_code == 401
    assert start(client).status_code == 401
    client.post("/api/v1/session")
    assert client.get(f"/api/v1/scans/{scan_id}").status_code == 404
    assert client.get(f"/api/v1/scans/{scan_id}/image").status_code == 404
    assert client.delete(f"/api/v1/scans/{scan_id}").status_code == 404


def test_session_reuse_and_cookie_flags(client):
    token = client.cookies.get("doculens_session")
    assert client.post("/api/v1/session").status_code == 200
    assert client.cookies.get("doculens_session") == token
    client.cookies.clear()
    cookie = client.post("/api/v1/session").headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api/v1" in cookie


def test_rejects_foreign_origin(client):
    assert (
        client.post("/api/v1/session", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert start(client, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_rejects_content_spoof_and_excessive_upload(client):
    assert start(client, b"<svg>not an image</svg>").status_code == 415
    assert start(client, b"\xff\xd8\xff" + b"0" * (1024**2)).status_code == 413
    response = client.post("/api/v1/scans", content=b"0" * (4 * 1024**2))
    assert response.status_code == 413


def test_corrupted_image_has_safe_failure(client):
    scan_id = start(client, b"\xff\xd8\xffbroken").json()["scan_id"]
    body = wait_result(client, scan_id)
    assert body["status"] == "failed"
    assert body["result"] is None
    assert "Traceback" not in body["error"]


def test_bad_options_do_not_echo_input(client):
    response = start(client, data={"options": '{"front":{"rotation":13},"secret":"PII"}'})
    assert response.status_code == 422
    assert "PII" not in response.text


def test_unavailable_language(client):
    assert start(client, **{"data": {"options": '{"language":"arabic"}'}}).status_code == 422


def test_ocr_failure_is_exposed_safely(client, engine):
    engine.fail = True
    body = wait_result(client, start(client).json()["scan_id"])
    assert body["status"] == "failed"
    assert body["result"] is None


def test_cancellation_cannot_restore_results(client, engine):
    engine.gate = threading.Event()
    scan_id = start(client).json()["scan_id"]
    assert client.delete(f"/api/v1/scans/{scan_id}").status_code == 204
    engine.gate.set()
    time.sleep(0.05)
    assert client.get(f"/api/v1/scans/{scan_id}").status_code == 404


def test_expiration_purges_images(client):
    scan_id = start(client).json()["scan_id"]
    wait_result(client, scan_id)
    store = client.app.state.store
    with store.lock:
        job = next(iter(store._jobs.values()))
        job.created -= 1000
    assert client.get(f"/api/v1/scans/{scan_id}").status_code == 404
    assert not job.images
    assert job.result is None


def test_capacity_is_bounded(client, engine):
    engine.gate = threading.Event()
    store = client.app.state.store
    for index in range(store.capacity):
        store.create(f"independent-owner-{index}")
    assert start(client).status_code == 429
    engine.gate.set()


def test_new_scan_discards_previous_session_document(client, engine):
    engine.gate = threading.Event()
    first = start(client).json()["scan_id"]
    previous = next(iter(client.app.state.store._jobs.values()))
    second = start(client).json()["scan_id"]
    assert first != second
    assert previous.cancelled.is_set()
    assert not previous.uploads
    assert previous.result is None and not previous.images
    assert client.get(f"/api/v1/scans/{first}").status_code == 404
    assert len(client.app.state.store._jobs) == 1
    engine.gate.set()
    assert wait_result(client, second)["status"] == "completed"


def test_upload_above_default_spool_threshold_never_writes_to_disk(monkeypatch, engine):
    def forbidden_rollover(_self):
        pytest.fail("Document uploads must not spill to a temporary disk file")
    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", forbidden_rollover)
    with TestClient(create_app(Settings(max_upload_mb=2), engine)) as memory_client:
        memory_client.post("/api/v1/session")
        # Valid synthetic PNG plus padding; exceeds Starlette's usual 1 MiB limit.
        submitted = start(memory_client, png() + b"\0" * (1024**2 + 100))
        assert submitted.status_code == 202
        assert wait_result(memory_client, submitted.json()["scan_id"])["status"] == "completed"
