"""Background jobs for long-running generations.

A full-length (60s+) high-quality video pipeline — multi-scene render,
video-use post-production, mastering — takes tens of minutes and cannot live
inside a single synchronous HTTP request. Jobs run in daemon worker threads
while the cockpit polls for progress.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import now_iso


@dataclass
class VideoJob:
    job_id: str
    topic: str
    prompt: str
    duration: int
    quality: str = "high"
    narration: str | None = None
    music_mode: str = "ambient"
    preferred_provider: str | None = None
    status: str = "queued"  # queued | running | completed | failed
    stage: str = "queued"
    progress: float = 0.0  # 0.0 - 100.0
    asset_id: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "topic": self.topic,
            "prompt": self.prompt,
            "duration": self.duration,
            "quality": self.quality,
            "preferred_provider": self.preferred_provider,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 1),
            "asset_id": self.asset_id,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobManager:
    """Thread-based background job runner (in-memory; ledger records history)."""

    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, VideoJob] = {}
        self._lock = threading.RLock()
        self._semaphore = threading.Semaphore(max_workers)

    def submit_video(self, topic: str, prompt: str, duration: int, quality: str = "high",
                     narration: str | None = None, music_mode: str = "ambient",
                     preferred_provider: str | None = None) -> VideoJob:
        job = VideoJob(
            job_id=f"job-{uuid.uuid4().hex[:10]}",
            topic=topic, prompt=prompt, duration=duration, quality=quality,
            narration=narration, music_mode=music_mode,
            preferred_provider=preferred_provider,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def update(self, job_id: str, **fields: Any) -> VideoJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = now_iso()
            return job

    def get(self, job_id: str) -> VideoJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[VideoJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def run(self, job_id: str, target: Callable[[VideoJob, Callable[[str, float], None]], None]) -> bool:
        """Run ``target(job, progress)`` in a daemon thread. Returns False if busy/unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "queued":
                return False
            job.status = "running"
            job.updated_at = now_iso()
        if not self._semaphore.acquire(blocking=False):
            self.update(job_id, status="queued", stage="waiting for worker")
            # Re-queue: run blocking in the thread instead.
            thread = threading.Thread(target=self._run_blocking, args=(job_id, target), daemon=True)
            thread.start()
            return True
        thread = threading.Thread(target=self._run_guarded, args=(job_id, target), daemon=True)
        thread.start()
        return True

    def _run_guarded(self, job_id: str, target: Callable[..., None]) -> None:
        try:
            self._run_target(job_id, target)
        finally:
            self._semaphore.release()

    def _run_blocking(self, job_id: str, target: Callable[..., None]) -> None:
        with self._semaphore:
            self._run_target(job_id, target)

    def _run_target(self, job_id: str, target: Callable[..., None]) -> None:
        job = self.get(job_id)
        if not job:
            return
        self.update(job_id, status="running")

        def progress(stage: str, pct: float) -> None:
            self.update(job_id, stage=stage, progress=max(0.0, min(100.0, pct)))

        try:
            target(job, progress)
            current = self.get(job_id)
            if current and current.status == "running":
                self.update(job_id, status="completed", stage="done", progress=100.0)
        except Exception as exc:
            traceback.print_exc()
            self.update(job_id, status="failed", stage="failed",
                        error=f"{type(exc).__name__}: {exc}"[:500])
