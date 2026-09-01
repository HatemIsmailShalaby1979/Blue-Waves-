from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from .models import now_iso


@dataclass
class PerformanceMemory:
    memory_id: str
    asset_id: str
    content_type: str
    topic: str
    winning_metrics: dict[str, float]
    provider: str
    created_at: str = field(default_factory=now_iso)
    status: str = "proposed"
    approved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetacognitiveEngine:
    """Owner-gated learning loop over imported audience metrics."""

    def __init__(self) -> None:
        self._metrics: list[dict[str, Any]] = []
        self._memory: list[PerformanceMemory] = []

    def add_metric(self, event: dict[str, Any]) -> None:
        self._metrics.append(event)

    def restore_metric(self, event: dict[str, Any]) -> None:
        if not any(existing.get("event_id") == event.get("event_id") for existing in self._metrics):
            self._metrics.append(event)

    def propose_memory(self, assets: dict[str, dict[str, Any]]) -> list[PerformanceMemory]:
        grouped: dict[str, dict[str, float]] = defaultdict(dict)
        for event in self._metrics:
            grouped[event["asset_id"]][event["metric"]] = float(event["value"])
        proposals: list[PerformanceMemory] = []
        for asset_id, metrics in grouped.items():
            if not metrics or asset_id not in assets:
                continue
            score = sum(metrics.values())
            if score <= 0:
                continue
            asset = assets[asset_id]
            proposals.append(PerformanceMemory(
                # Stable IDs let the owner approve the exact proposal shown in the cockpit.
                memory_id=f"memory-{asset_id}", asset_id=asset_id,
                content_type=asset.get("content_type", "video"), topic=asset.get("topic", ""),
                winning_metrics=metrics, provider=asset.get("provider", "unknown"),
            ))
        return proposals

    def rank_assets(self, assets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        proposals = self.propose_memory(assets)
        return sorted((p.to_dict() for p in proposals), key=lambda item: sum(item["winning_metrics"].values()), reverse=True)

    def approve(self, memory: PerformanceMemory) -> PerformanceMemory:
        memory.status = "approved"
        memory.approved_at = now_iso()
        self._memory.append(memory)
        return memory

    def memories(self) -> list[dict[str, Any]]:
        return [memory.to_dict() for memory in self._memory]

    def shipo_recommendations(self, assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
        ranked = self.rank_assets(assets)
        top = ranked[0] if ranked else None
        topic = top["topic"] if top else "audience questions with a clear practical outcome"
        provider = top["provider"] if top else "local-first"
        return {
            "agent": "SHIPO",
            "strategy": "Owner-approved reinvestment only; preserve the winning format and provider until new evidence contradicts it.",
            "viral_topic_suggestions": [
                f"A practical follow-up to: {topic}",
                "A contrarian myth-vs-evidence episode in the strongest audience category",
                "A short answer to the most repeated audience question from the last review",
            ],
            "recommended_production_pattern": provider,
            "evidence": ranked[:5],
            "requires_owner_approval": True,
        }
