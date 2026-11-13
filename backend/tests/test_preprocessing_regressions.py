"""Preserve readable source pixels and route optional OCR recovery engines."""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.core.config import Settings
from app.core.store import ScanStore
from app.schemas.models import ScanOptions
from app.services import pipeline
from app.services.ocr import OCRService


@pytest.mark.parametrize("brightness", [40, 180, 255])
def test_full_scan_preserves_size_and_only_brightens_dark_images(brightness):
    image = np.full((200, 320, 3), brightness, np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    captured = []

    class Reader:
        def read_oriented(self, pixels, **kwargs):
            captured.append(pixels.copy())
            return pixels, [], 0

    store = ScanStore(60, 1, 4 * 1024 * 1024)
    job = store.create("synthetic-lighting")
    try:
        pipeline.run_scan(
            job, {"front": encoded.tobytes()}, ScanOptions(), store, Reader(),
            Settings(enable_tesseract_backup=False, enable_multivariant_voting=False),
        )
        assert job.status == "completed", job.error
        assert captured[0].shape == image.shape
        if brightness < 85:
            assert captured[0].mean() > image.mean()
        else:
            np.testing.assert_array_equal(captured[0], image)
    finally:
        store.clear()


def test_oriented_scan_passes_backup_engines_to_region_recovery(monkeypatch):
    reader = OCRService()
    def fake_engine(*_args, **_kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(reader, "_get_engine", lambda *args, **kwargs: fake_engine)
    monkeypatch.setattr(reader, "_read", lambda *args, **kwargs: [])
    monkeypatch.setattr(reader, "_recover_small_captions", lambda *args: None)
    calls = {}
    monkeypatch.setattr(reader, "_retry_uncertain_regions",
                        lambda *args, **kwargs: calls.update(regions=kwargs))
    monkeypatch.setattr(reader, "_retry_mrz_names",
                        lambda *args, **kwargs: calls.update(mrz=kwargs))
    reader.read_oriented(np.full((100, 200, 3), 255, np.uint8), auto_rotate=False)
    assert calls["regions"]["tesseract"] is reader.tesseract
    assert calls["mrz"]["tesseract"] is reader.tesseract
