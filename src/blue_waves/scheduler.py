from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .governance import Governance
from .models import ContentRequest, now_iso
from .queue import ContentQueue


@dataclass
class ScheduledJob:
    job_id: str
    request_id: str
    content_type: str
    scheduled_for: str
    status: str = "pending"
    created_at: str = field(default_factory=now_iso)


class Scheduler:
    """Autonomous scheduler with batch processing and time windows."""

    def __init__(self, settings: Settings, governance: Governance, queue: ContentQueue) -> None:
        self._settings = settings
        self._governance = governance
        self._queue = queue
        self._jobs: list[ScheduledJob] = []

    def schedule_batch(self, content_type: str, count: int = 3) -> list[ScheduledJob]:
        scheduled = []
        pending = self._queue.get_by_stage("queued")
        type_pending = [r for r in pending if r.content_type == content_type]

        for request in type_pending[:count]:
            job = ScheduledJob(
                job_id=f"job-{uuid.uuid4().hex[:8]}",
                request_id=request.id,
                content_type=content_type,
                scheduled_for=now_iso(),
            )
            self._jobs.append(job)
            scheduled.append(job)
            request.advance_stage()

        return scheduled

    def get_jobs_by_status(self, status: str) -> list[ScheduledJob]:
        return [j for j in self._jobs if j.status == status]

    def get_pending_jobs(self) -> list[ScheduledJob]:
        return self.get_jobs_by_status("pending")

    def get_completed_jobs(self) -> list[ScheduledJob]:
        return self.get_jobs_by_status("completed")

    def complete_job(self, job_id: str) -> bool:
        for job in self._jobs:
            if job.job_id == job_id:
                job.status = "completed"
                return True
        return False

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_jobs": len(self._jobs),
            "pending": len(self.get_pending_jobs()),
            "completed": len(self.get_completed_jobs()),
            "queue_size": self._queue.size(),
        }
