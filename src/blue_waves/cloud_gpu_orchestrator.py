"""Asynchronous contract for optional free-GPU media jobs.

Notebook platforms and hosted open-source model endpoints are intentionally not
implemented as synchronous providers. This module defines the safe boundary for
future adapters: submit a job, poll it, validate a downloaded artifact, and
surface timeout/manual-intervention states without retrying an unknown request.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


class CloudGpuJobError(RuntimeError):
    pass


class CloudGpuAdapter(Protocol):
    name: str

    def submit(self, request: dict[str, Any]) -> str: ...

    def status(self, remote_job_id: str) -> dict[str, Any]: ...

    def cancel(self, remote_job_id: str) -> None: ...

    def download(self, remote_job_id: str, target: Path) -> Path: ...


@dataclass
class CloudGpuJob:
    job_id: str
    adapter: str
    content_type: str
    request: dict[str, Any]
    status: str = "queued"
    remote_job_id: str | None = None
    artifact_path: str | None = None
    artifact_sha256: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CloudGpuOrchestrator:
    """Persisted job state machine with explicit unknown-outcome handling."""

    def __init__(self, root: Path, adapters: dict[str, CloudGpuAdapter] | None = None) -> None:
        self.root = root
        self.path = root / "cloud_gpu_jobs.json"
        self._adapters = adapters or {}
        self._jobs: dict[str, CloudGpuJob] = {}
        self._lock = threading.RLock()
        self._load()

    def register(self, adapter: CloudGpuAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def submit(self, adapter: str, content_type: str, request: dict[str, Any]) -> CloudGpuJob:
        if adapter not in self._adapters:
            raise CloudGpuJobError(f"cloud GPU adapter is not registered: {adapter}")
        job = CloudGpuJob(uuid.uuid4().hex, adapter, content_type, dict(request))
        with self._lock:
            self._jobs[job.job_id] = job
            self._save()
        try:
            remote_id = self._adapters[adapter].submit(dict(request))
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.updated_at = _now()
            self._save()
            return job
        job.remote_job_id = str(remote_id)
        job.status = "submitted"
        job.updated_at = _now()
        self._save()
        return job

    def poll(self, job_id: str) -> CloudGpuJob:
        job = self.get(job_id)
        if job.status not in {"submitted", "running", "unknown_outcome"}:
            return job
        if not job.remote_job_id:
            raise CloudGpuJobError("job has no remote identifier")
        try:
            state = self._adapters[job.adapter].status(job.remote_job_id)
        except Exception as exc:
            job.status = "unknown_outcome"
            job.error = f"status check failed: {exc}"
            job.updated_at = _now()
            self._save()
            return job
        remote_status = str(state.get("status", "unknown")).lower()
        job.status = {
            "queued": "submitted",
            "pending": "submitted",
            "running": "running",
            "processing": "running",
            "completed": "completed",
            "succeeded": "completed",
            "failed": "failed",
            "error": "failed",
            "cancelled": "cancelled",
        }.get(remote_status, "unknown_outcome")
        job.error = state.get("error")
        job.updated_at = _now()
        self._save()
        return job

    def retrieve(self, job_id: str, target: Path) -> CloudGpuJob:
        job = self.get(job_id)
        if job.status != "completed":
            raise CloudGpuJobError(f"job is not completed: {job.status}")
        if not job.remote_job_id:
            raise CloudGpuJobError("completed job has no remote identifier")
        try:
            artifact = self._adapters[job.adapter].download(job.remote_job_id, target)
        except Exception as exc:
            job.status = "failed"
            job.error = f"artifact download failed: {exc}"
            job.updated_at = _now()
            self._save()
            return job
        artifact = Path(artifact)
        if not artifact.is_file() or artifact.stat().st_size == 0:
            job.status = "failed"
            job.error = "artifact is missing or empty"
        else:
            job.artifact_path = str(artifact)
            job.artifact_sha256 = _sha256(artifact)
            job.status = "artifact_validated"
            job.error = None
        job.updated_at = _now()
        self._save()
        return job

    def cancel(self, job_id: str) -> CloudGpuJob:
        job = self.get(job_id)
        if job.remote_job_id and job.status in {"submitted", "running", "unknown_outcome"}:
            try:
                self._adapters[job.adapter].cancel(job.remote_job_id)
                job.status = "cancelled"
                job.error = None
            except Exception as exc:
                job.status = "unknown_outcome"
                job.error = f"cancel failed: {exc}"
        else:
            job.status = "cancelled"
        job.updated_at = _now()
        self._save()
        return job

    def get(self, job_id: str) -> CloudGpuJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise CloudGpuJobError(f"unknown cloud GPU job: {job_id}") from exc

    def list_jobs(self) -> list[CloudGpuJob]:
        return list(self._jobs.values())

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in raw.get("jobs", []):
            job = CloudGpuJob(**item)
            self._jobs[job.job_id] = job

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"jobs": [job.to_dict() for job in self._jobs.values()]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
