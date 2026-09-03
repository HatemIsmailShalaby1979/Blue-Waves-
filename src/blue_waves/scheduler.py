from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    priority: int = 0  # Higher = more urgent
    recurrence: str | None = None  # "daily", "weekly", "custom"


@dataclass
class PublishWindow:
    """Time window when publishing is allowed."""
    days_of_week: list[int] = field(default_factory=lambda: [0, 2, 4])  # Mon, Wed, Fri
    start_hour: int = 10
    end_hour: int = 18
    timezone: str = "UTC"


class Scheduler:
    """Autonomous scheduler with batch processing, time windows, and recurring schedules.
    
    Supports 3+ publishes per week with configurable windows and recurrence.
    """

    def __init__(
        self, 
        settings: Settings, 
        governance: Governance, 
        queue: ContentQueue,
        publish_window: PublishWindow | None = None
    ) -> None:
        self._settings = settings
        self._governance = governance
        self._queue = queue
        self._jobs: list[ScheduledJob] = []
        self._publish_window = publish_window or PublishWindow()
        self._weekly_published = 0
        self._week_start = datetime.utcnow().date() - timedelta(days=datetime.utcnow().weekday())

    def _reset_weekly_counter(self) -> None:
        """Reset weekly counter if new week started."""
        now = datetime.utcnow().date()
        week_start = now - timedelta(days=now.weekday())
        if week_start > self._week_start:
            self._week_start = week_start
            self._weekly_published = 0

    def _is_in_publish_window(self, dt: datetime | None = None) -> bool:
        """Check if current time (or given dt) is within publish window."""
        check_dt = dt or datetime.utcnow()
        if check_dt.weekday() not in self._publish_window.days_of_week:
            return False
        hour = check_dt.hour
        return self._publish_window.start_hour <= hour < self._publish_window.end_hour

    def _get_next_publish_time(self) -> datetime:
        """Get the next valid publish time within window."""
        now = datetime.utcnow()
        # If currently in window, return now
        if self._is_in_publish_window(now):
            return now
        
        # Find next valid day
        for days_ahead in range(1, 8):
            candidate = now + timedelta(days=days_ahead)
            if candidate.weekday() in self._publish_window.days_of_week:
                return candidate.replace(
                    hour=self._publish_window.start_hour,
                    minute=0, second=0, microsecond=0
                )
        return now  # Fallback

    def schedule_batch(
        self, 
        content_type: str, 
        count: int = 3,
        priority: int = 0,
        recurrence: str | None = None
    ) -> list[ScheduledJob]:
        """Schedule a batch of requests for publishing."""
        self._reset_weekly_counter()
        
        # Check weekly limit
        remaining = self._settings.max_weekly_publishes - self._weekly_published
        if remaining <= 0:
            return []  # Weekly cap reached
        
        count = min(count, remaining)
        
        scheduled = []
        pending = self._queue.get_by_stage("queued")
        type_pending = [r for r in pending if r.content_type == content_type]
        
        # Sort by priority (highest first)
        type_pending.sort(key=lambda r: getattr(r, 'priority', 0), reverse=True)
        
        for request in type_pending[:count]:
            next_pub = self._get_next_publish_time()
            job = ScheduledJob(
                job_id=f"job-{uuid.uuid4().hex[:8]}",
                request_id=request.id,
                content_type=content_type,
                scheduled_for=next_pub.isoformat(),
                priority=priority,
                recurrence=recurrence,
            )
            self._jobs.append(job)
            scheduled.append(job)
            request.advance_stage()
            self._weekly_published += 1
        
        return scheduled

    def schedule_recurring(
        self,
        content_type: str,
        count_per_week: int = 3,
        days: list[int] | None = None,
    ) -> list[ScheduledJob]:
        """Set up recurring weekly schedule (e.g., 3 posts on Mon/Wed/Fri)."""
        window = PublishWindow(days_of_week=days or [0, 2, 4])
        original_window = self._publish_window
        self._publish_window = window
        try:
            return self.schedule_batch(content_type, count_per_week, recurrence="weekly")
        finally:
            self._publish_window = original_window

    def get_due_jobs(self) -> list[ScheduledJob]:
        """Get jobs that are due for execution."""
        now = datetime.utcnow()
        due = []
        for job in self._jobs:
            if job.status == "pending":
                scheduled = datetime.fromisoformat(job.scheduled_for.replace('Z', '+00:00'))
                if scheduled <= now and self._is_in_publish_window(scheduled):
                    due.append(job)
        return due

    def execute_due_jobs(self, max_concurrent: int = 3) -> list[ScheduledJob]:
        """Execute all due jobs up to max_concurrent."""
        due = self.get_due_jobs()[:max_concurrent]
        for job in due:
            job.status = "running"
        return due

    def complete_job(self, job_id: str) -> bool:
        for job in self._jobs:
            if job.job_id == job_id:
                job.status = "completed"
                return True
        return False

    def get_jobs_by_status(self, status: str) -> list[ScheduledJob]:
        return [j for j in self._jobs if j.status == status]

    def get_pending_jobs(self) -> list[ScheduledJob]:
        return self.get_jobs_by_status("pending")

    def get_completed_jobs(self) -> list[ScheduledJob]:
        return self.get_jobs_by_status("completed")

    def get_stats(self) -> dict[str, Any]:
        self._reset_weekly_counter()
        return {
            "total_jobs": len(self._jobs),
            "pending": len(self.get_pending_jobs()),
            "running": len(self.get_jobs_by_status("running")),
            "completed": len(self.get_completed_jobs()),
            "weekly_published": self._weekly_published,
            "weekly_limit": self._settings.max_weekly_publishes,
            "queue_size": self._queue.size(),
            "publish_window_days": self._publish_window.days_of_week,
            "next_publish_time": self._get_next_publish_time().isoformat(),
        }
