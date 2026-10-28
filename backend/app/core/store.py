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
                if time.monotonic() - job.created > self.retention:
                    job.cancelled.set()
                    job.images.clear()
                    job.result = None
                    del self._jobs[key]

    def create(self, owner: str) -> ScanJob:
        with self.lock:
            self.prune()
            if len(self._jobs) >= self.capacity:
                raise CapacityError(
                    "The scanner is at capacity. Clear an earlier scan or try later."
                )
            if sum(job.owner == owner for job in self._jobs.values()) >= 2:
                raise CapacityError("Clear an earlier scan before starting another.")
            job = ScanJob(owner=owner)
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

    def delete(self, scan_id: str, owner: str) -> bool:
        with self.lock:
            job = self.get(scan_id, owner)
            if not job:
                return False
            job.cancelled.set()
            job.images.clear()
            job.result = None
            del self._jobs[scan_id]
            return True

    def clear(self) -> None:
        with self.lock:
            for job in self._jobs.values():
                job.cancelled.set()
                job.images.clear()
                job.result = None
            self._jobs.clear()
