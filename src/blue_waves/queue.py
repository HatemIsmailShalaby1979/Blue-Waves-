from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .models import ContentRequest, now_iso


class ContentQueue:
    """Multi-format content queue with priority ordering."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._requests: list[ContentRequest] = []

    def add(self, request: ContentRequest) -> None:
        self._requests.append(request)

    def get_by_stage(self, stage: str) -> list[ContentRequest]:
        return [r for r in self._requests if r.stage == stage]

    def get_by_content_type(self, content_type: str) -> list[ContentRequest]:
        return [r for r in self._requests if r.content_type == content_type]

    def get_weekly_count(self, content_type: str) -> int:
        return len(self.get_by_content_type(content_type))

    def size(self) -> int:
        return len(self._requests)

    def get_next(self) -> ContentRequest | None:
        priority_order = {"high": 0, "normal": 1, "low": 2}
        queued = [r for r in self._requests if r.stage == "queued"]
        if not queued:
            return None
        queued.sort(key=lambda r: priority_order.get(r.priority, 1))
        return queued[0]

    def remove(self, request_id: str) -> bool:
        for i, r in enumerate(self._requests):
            if r.id == request_id:
                self._requests.pop(i)
                return True
        return False

    def get_all(self) -> list[ContentRequest]:
        return list(self._requests)

    def get_pending(self) -> list[ContentRequest]:
        return [r for r in self._requests if r.stage in ("queued", "scripted", "composed")]

    def get_ready_to_publish(self) -> list[ContentRequest]:
        return [r for r in self._requests if r.stage == "ready_to_publish"]

    def get_published(self) -> list[ContentRequest]:
        return [r for r in self._requests if r.stage == "published"]

    def get_rejected(self) -> list[ContentRequest]:
        return [r for r in self._requests if r.stage == "rejected"]
