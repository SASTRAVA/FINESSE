"""Deterministic idempotent job records with bounded retry and DLQ semantics."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

from ..db.storage import PlatformStorage, storage


def _canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class Job:
    id: str
    tenant_id: str
    actor_sub: str
    job_type: str
    idempotency_key: str
    payload: dict
    status: str = "queued"
    progress: float = 0.0
    attempts: int = 0
    max_retries: int = 3
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobQueue:
    def __init__(self, repository: PlatformStorage = storage):
        self.repository = repository
        self._lock = threading.RLock()

    @staticmethod
    def idempotency_key(tenant_id: str, actor_sub: str, job_type: str,
                        payload: dict) -> str:
        payload_hash = _canonical_hash(payload)
        material = f"{tenant_id}{actor_sub}{job_type}{payload_hash}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def enqueue(self, *, tenant_id: str, actor_sub: str, job_type: str,
                payload: dict, max_retries: int = 3) -> Job:
        if not all((tenant_id, actor_sub, job_type)):
            raise ValueError("tenant_id, actor_sub, and job_type are required")
        if not 0 <= max_retries <= 3:
            raise ValueError("max_retries must be between 0 and 3")
        key = self.idempotency_key(tenant_id, actor_sub, job_type, payload)
        with self._lock:
            for record in self.repository.list("jobs", tenant_id, limit=1000):
                if record.get("idempotency_key") == key:
                    return Job(**record)
            job = Job(uuid.uuid4().hex, tenant_id, actor_sub, job_type, key,
                      dict(payload), max_retries=max_retries)
            self.repository.put("jobs", tenant_id, job.id, asdict(job))
            return job

    def get(self, tenant_id: str, job_id: str) -> Job | None:
        record = self.repository.get("jobs", tenant_id, job_id)
        return Job(**record) if record else None

    def update_progress(self, tenant_id: str, job_id: str, progress: float) -> Job:
        if not 0 <= progress <= 1:
            raise ValueError("progress must be between 0 and 1")
        job = self.get(tenant_id, job_id)
        if job is None:
            raise KeyError("job not found")
        if job.status in {"cancelled", "dead_letter", "completed"}:
            raise ValueError(f"cannot update a {job.status} job")
        job.progress = progress
        job.status = "running"
        job.updated_at = time.time()
        self.repository.put("jobs", tenant_id, job.id, asdict(job))
        return job

    def pause(self, tenant_id: str, job_id: str) -> Job:
        return self._set_status(tenant_id, job_id, "paused")

    def cancel(self, tenant_id: str, job_id: str) -> Job:
        return self._set_status(tenant_id, job_id, "cancelled")

    def _set_status(self, tenant_id: str, job_id: str, status: str) -> Job:
        job = self.get(tenant_id, job_id)
        if job is None:
            raise KeyError("job not found")
        if job.status in {"completed", "dead_letter", "cancelled"}:
            raise ValueError(f"cannot change a {job.status} job")
        job.status = status
        job.updated_at = time.time()
        self.repository.put("jobs", tenant_id, job.id, asdict(job))
        return job

    def fail(self, tenant_id: str, job_id: str, error: str, *,
             policy_or_validation: bool = False) -> Job:
        job = self.get(tenant_id, job_id)
        if job is None:
            raise KeyError("job not found")
        job.attempts += 1
        job.error = error[:500]
        if policy_or_validation or job.attempts > job.max_retries:
            job.status = "dead_letter"
        else:
            job.status = "queued"
        job.updated_at = time.time()
        self.repository.put("jobs", tenant_id, job.id, asdict(job))
        return job


jobs = JobQueue()
