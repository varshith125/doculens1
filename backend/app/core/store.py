import threading
import time
import uuid
from dataclasses import dataclass, field

from app.schemas.models import ScanResult


class CapacityError(Exception):
    pass


@dataclass
class ScanJob:
    owner: str
    scan_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: float = field(default_factory=time.monotonic)
    status: str = "queued"
    stage: str = "queued"
    result: ScanResult | None = None
    error: str | None = None
    images: dict[tuple[str, str], bytes] = field(default_factory=dict)
    cancelled: threading.Event = field(default_factory=threading.Event)
    uploads: dict[str, bytes] = field(default_factory=dict, repr=False)
    completed_at: float | None = None


class ScanStore:
    def __init__(self, retention: int, capacity: int, max_bytes: int):
        self.retention = retention
        self.capacity = capacity
        self.max_bytes = max_bytes
        self.lock = threading.RLock()
        self._jobs: dict[str, ScanJob] = {}

    def prune(self) -> None:
        with self.lock:
            for key, job in list(self._jobs.items()):
                now = time.monotonic()
                if (now - job.created > 300
                        or (job.completed_at is not None and now - job.completed_at > self.retention)):
                    self._discard(job)
                    del self._jobs[key]

    @staticmethod
    def _discard(job: ScanJob) -> None:
        job.cancelled.set()
        job.uploads.clear()
        job.images.clear()
        job.result = None
        job.error = None

    def create(self, owner: str, uploads: dict[str, bytes] | None = None) -> ScanJob:
        with self.lock:
            self.prune()
            # One current document per session. A new upload never retains or
            # queues behind that session's previous identity document.
            for key, previous in list(self._jobs.items()):
                if previous.owner == owner:
                    self._discard(previous)
                    del self._jobs[key]
            if len(self._jobs) >= self.capacity:
                raise CapacityError(
                    "The scanner is at capacity. Clear an earlier scan or try later."
                )
            job = ScanJob(owner=owner, uploads=uploads if uploads is not None else {})
            self._jobs[job.scan_id] = job
            return job

    def get(self, scan_id: str, owner: str) -> ScanJob | None:
        with self.lock:
            self.prune()
            job = self._jobs.get(scan_id)
            return job if job and job.owner == owner else None

    def complete(self, job: ScanJob, result: ScanResult, images: dict) -> None:
        with self.lock:
            if job.cancelled.is_set() or job.scan_id not in self._jobs:
                return
            current = sum(
                len(blob) for item in self._jobs.values() for blob in item.images.values()
            )
            if current + sum(map(len, images.values())) > self.max_bytes:
                raise CapacityError(
                    "Image memory limit reached. Clear an earlier scan and try again."
                )
            job.result = result
            job.images = images
            job.status = job.stage = "completed"
            job.completed_at = time.monotonic()
            job.uploads.clear()

    def delete(self, scan_id: str, owner: str) -> bool:
        with self.lock:
            job = self.get(scan_id, owner)
            if not job:
                return False
            self._discard(job)
            del self._jobs[scan_id]
            return True

    def clear(self) -> None:
        with self.lock:
            for job in self._jobs.values():
                self._discard(job)
            self._jobs.clear()
