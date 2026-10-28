"""Opt-in complete-pipeline regressions against a private, visually verified manifest.

DOCULENS_SAMPLE_MANIFEST points to a JSON list of {id, image, expected_fields}.
Images and expected identity data stay outside the distributed test fixtures.
"""

import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.store import ScanStore
from app.schemas.models import ScanOptions
from app.services.ocr import OCRService
from app.services.pipeline import run_scan

manifest = os.environ.get("DOCULENS_SAMPLE_MANIFEST")
cases = json.loads(Path(manifest).read_text(encoding="utf-8")) if manifest else []
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not manifest, reason="No authorized sample manifest configured"),
]


@pytest.fixture(scope="module")
def sample_engine():
    engine = OCRService()
    engine.warmup()
    return engine


@pytest.mark.parametrize("case", cases, ids=[case["id"] for case in cases])
@pytest.mark.parametrize("variant", ["original", "mild_blur"])
def test_authorized_sample_full_pipeline(case, variant, sample_engine):
    store = ScanStore(retention=600, capacity=2, max_bytes=64 * 1024 * 1024)
    job = store.create("authorized-regression")
    try:
        data = Path(case["image"]).read_bytes()
        if variant == "mild_blur":
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            blurred = cv2.GaussianBlur(image, (7, 7), 1.2)
            ok, encoded = cv2.imencode(".png", blurred)
            if ok and encoded.nbytes > 12 * 1024 * 1024:
                ok, encoded = cv2.imencode(".jpg", blurred, [cv2.IMWRITE_JPEG_QUALITY, 95])
            assert ok
            data = encoded.tobytes()
        run_scan(
            job,
            {"front": data},
            ScanOptions(date_order="dmy"),
            store,
            sample_engine,
        )
        if job.status != "completed" or job.result is None:
            pytest.fail("Authorized sample pipeline failed", pytrace=False)
        fields = job.result.model_dump(mode="json")["fields"]
        wrong = [
            name
            for name, expected in case["expected_fields"].items()
            if fields.get(name, {}).get("value") != expected
        ]
        if wrong:
            pytest.fail("Exact field mismatch: " + ", ".join(wrong), pytrace=False)
    finally:
        store.clear()
