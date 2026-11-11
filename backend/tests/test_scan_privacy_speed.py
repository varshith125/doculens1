"""In-memory synthetic checks for scan lifetime and fast OCR routing."""

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from app.core.store import CapacityError, ScanStore
from app.schemas.models import OCRLine
from app.services.ocr import OCRCancelled, OCRService, _clear_labeled_reading, _interruptible


def test_discard_clears_queued_uploads_and_prevents_old_completion():
    store = ScanStore(60, 2, 1024)
    uploads = {"front": b"synthetic only"}
    first = store.create("owner", uploads)
    first.images = {("front", "original"): b"synthetic"}
    next_job = store.create("owner")
    store.complete(first, None, {("front", "corrected"): b"late"})
    assert first.cancelled.is_set() and not uploads and not first.images
    assert store.get(first.scan_id, "owner") is None
    assert store.get(next_job.scan_id, "owner") is next_job


def test_new_owner_does_not_delete_another_owners_scan():
    store = ScanStore(60, 1, 1024)
    first = store.create("first")
    with pytest.raises(CapacityError):
        store.create("second")
    assert not first.cancelled.is_set()


def test_result_expiry_starts_after_processing_and_clears_data():
    store = ScanStore(60, 1, 1024)
    job = store.create("owner")
    job.created -= 90
    assert store.get(job.scan_id, "owner") is job
    store.complete(job, None, {("front", "original"): b"synthetic"})
    assert store.get(job.scan_id, "owner") is job
    job.completed_at = time.monotonic() - 61
    store.prune()
    assert not job.images and not store._jobs


def test_cancelled_inference_never_enters_the_model():
    cancelled = threading.Event()
    cancelled.set()
    def engine(*_args, **_kwargs):
        pytest.fail("Cancelled scans must not run inference")
    with pytest.raises(OCRCancelled):
        _interruptible(engine, cancelled)(np.zeros((10, 10, 3)))


def test_cancellation_after_inference_prevents_optional_rereads():
    cancelled = threading.Event()
    def engine(*_args, **_kwargs):
        cancelled.set()
        return SimpleNamespace(txts=["SYNTHETIC"])
    with pytest.raises(OCRCancelled):
        _interruptible(engine, cancelled)(np.zeros((10, 10, 3)))


def test_medium_recognition_is_lazy_and_only_for_recovery(monkeypatch):
    service = OCRService(fast_text=True, medium_rec_path="synthetic-medium.onnx")
    calls = []
    def load(language, **kwargs):
        calls.append((language, kwargs))
        return lambda *_args, **_kwargs: "recovered"
    monkeypatch.setattr(service, "_get_engine", load)
    reader = service._recovery_reader("latin", lambda: "initial")
    assert not calls
    assert reader(np.zeros((10, 10, 3))) == "recovered"
    assert calls == [("latin", {"detailed": True})]


def test_disabled_fast_mode_and_arabic_keep_their_selected_model():
    engine = object()
    service = OCRService(fast_text=False)
    assert service._recovery_reader("latin", engine) is engine
    service._fast_text = True
    assert service._recovery_reader("arabic", engine) is engine


def test_fast_first_pass_uses_recovery_model_only_for_uncertain_regions(monkeypatch):
    service = OCRService(fast_text=True)
    initial = object()
    recovery = object()
    lines = [OCRLine(text="SYNTHETIC", confidence=0.99,
                     bounding_box=[[0, 0], [50, 0], [50, 10], [0, 10]])] * 6
    seen = []
    monkeypatch.setattr(service, "_recover_small_captions", lambda e, *_: seen.append(("detect", e)))
    monkeypatch.setattr(service, "_retry_uncertain_regions", lambda e, *_, **kwargs: seen.append(("retry", e)))
    monkeypatch.setattr(service, "_retry_mrz_names", lambda e, *_, **kwargs: seen.append(("mrz", e)))
    service._read(initial, np.full((100, 100, 3), 255, np.uint8), "front",
                  initial_lines=lines, recovery_engine=recovery)
    assert seen == [("detect", initial), ("retry", recovery), ("mrz", recovery)]


def test_short_clear_document_avoids_full_page_orientation_retries(monkeypatch):
    service = OCRService(medium_rec_path="")
    calls = []
    def engine(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            boxes=[[[10, y], [190, y], [190, y + 15], [10, y + 15]] for y in (10, 50)],
            txts=["Surname: SPECIMEN", "Nationality: UTOPIA"], scores=[0.99, 0.99],
        )
    monkeypatch.setattr(service, "_get_engine", lambda _: engine)
    monkeypatch.setattr(service, "_orientation", lambda *_: 0)
    monkeypatch.setattr(service, "_recover_small_captions", lambda *_: None)
    monkeypatch.setattr(service, "_retry_uncertain_regions", lambda *_, **kwargs: None)
    monkeypatch.setattr(service, "_retry_mrz_names", lambda *_, **kwargs: None)
    _, lines, _ = service.read_oriented(np.full((100, 220, 3), 255, np.uint8))
    assert len(lines) == 2
    assert len(calls) == 1
    assert _clear_labeled_reading(lines)
    lines[0].confidence = 0.5
    assert not _clear_labeled_reading(lines)
