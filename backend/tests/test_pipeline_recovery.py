"""Synthetic regressions for optional MRZ recovery and scan diagnostics."""

import io
import logging

import pytest
from PIL import Image

from app.core.config import Settings
from app.core.store import ScanStore
from app.extractors import mrz_parser
from app.schemas.models import MRZResult, OCRLine, ScanOptions
from app.services import pipeline


@pytest.fixture
def scan_case():
    image = io.BytesIO()
    Image.new("RGB", (320, 200), "white").save(image, "PNG")
    uploads = {"front": image.getvalue()}
    store = ScanStore(60, 1, 1024**2)
    job = store.create("synthetic-owner", uploads)
    return job, uploads, store


@pytest.mark.parametrize(
    "enabled,detected,checksum,recovery_fails,expected_calls",
    [
        (True, False, None, False, 0),
        (True, True, True, False, 0),
        (False, True, False, False, 0),
        (False, True, None, False, 0),
        (True, True, False, False, 1),
        (True, True, None, False, 1),
        (True, True, False, True, 1),
    ],
)
def test_recovery_requires_enabled_unchecked_mrz_and_preserves_printed_fields(
    monkeypatch, scan_case, enabled, detected, checksum, recovery_fails, expected_calls,
):
    clock = [0.0]
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(
        mrz_parser, "detect_mrz",
        lambda _lines: (MRZResult(detected=detected, checksum_valid=checksum), []),
    )

    class SyntheticOCR:
        calls = 0

        def read_oriented(self, image, **_kwargs):
            clock[0] += 0.1
            return image, [OCRLine(
                text="Surname: SPECIMEN", confidence=0.99,
                bounding_box=[[20, 20], [250, 20], [250, 40], [20, 40]],
            )], 0

        def read_plain(self, _image, **_kwargs):
            self.calls += 1
            clock[0] += 0.05
            if recovery_fails:
                raise RuntimeError("Synthetic optional recovery failure")
            return []

    job, uploads, store = scan_case
    ocr = SyntheticOCR()
    pipeline.run_scan(
        job, uploads, ScanOptions(), store, ocr,
        Settings(enable_multivariant_voting=enabled),
    )
    assert ocr.calls == expected_calls
    assert job.status == "completed"
    assert job.result.fields["surname"].value == "SPECIMEN"
    assert job.result.timings_ms["ocr"] == 100 + 50 * expected_calls
    if expected_calls:
        assert job.result.timings_ms["mrz_recovery"] == 50
    else:
        assert "mrz_recovery" not in job.result.timings_ms


def test_unexpected_failure_logs_traceback_and_keeps_api_error_generic(
    monkeypatch, caplog, scan_case,
):
    def fail_decode(_data):
        raise RuntimeError("Synthetic internal failure")

    monkeypatch.setattr(pipeline, "decode_image", fail_decode)
    job, uploads, store = scan_case
    with caplog.at_level(logging.ERROR, logger=pipeline.__name__):
        pipeline.run_scan(job, uploads, ScanOptions(), store, object())
    assert job.status == "failed"
    assert "Synthetic internal failure" not in job.error
    assert not uploads
    record = next(record for record in caplog.records if record.name == pipeline.__name__)
    assert record.exc_info[0] is RuntimeError
    assert record.getMessage() == "Unexpected scan failure at stage detecting_document"
