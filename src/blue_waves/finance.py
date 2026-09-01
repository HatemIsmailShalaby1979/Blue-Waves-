from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import now_iso


@dataclass
class CostEntry:
    event_id: str
    provider: str
    content_type: str
    asset_id: str
    credits: int
    estimated_cents: int
    recorded_at: str = field(default_factory=now_iso)


@dataclass
class FreeTierStatus:
    provider: str
    daily_credits: int
    monthly_credits: int
    daily_used: int = 0
    monthly_used: int = 0
    reset_daily: str = ""
    reset_monthly: str = ""

    @property
    def daily_remaining(self) -> int:
        return max(0, self.daily_credits - self.daily_used)

    @property
    def monthly_remaining(self) -> int:
        return max(0, self.monthly_credits - self.monthly_used)


class FinanceEngine:
    """SHIPO — cost tracking and free-tier maximization."""

    def __init__(self) -> None:
        self._costs: list[CostEntry] = []
        self._free_tiers: dict[str, FreeTierStatus] = {}

    def log_cost(self, provider: str, content_type: str, asset_id: str,
                 credits: int, estimated_cents: int) -> None:
        entry = CostEntry(
            event_id=f"cost-{asset_id}-{provider}",
            provider=provider,
            content_type=content_type,
            asset_id=asset_id,
            credits=credits,
            estimated_cents=estimated_cents,
        )
        self._costs.append(entry)
        if provider in self._free_tiers:
            tier = self._free_tiers[provider]
            tier.daily_used += credits
            tier.monthly_used += credits

    def get_remaining_free_tier(self, provider: str) -> dict[str, Any]:
        if provider not in self._free_tiers:
            return {"daily_credits": -1, "monthly_credits": -1, "daily_remaining": -1, "monthly_remaining": -1}
        tier = self._free_tiers[provider]
        return {
            "daily_credits": tier.daily_credits,
            "monthly_credits": tier.monthly_credits,
            "daily_remaining": tier.daily_remaining,
            "monthly_remaining": tier.monthly_remaining,
        }

    def set_free_tier(self, provider: str, daily_credits: int, monthly_credits: int) -> None:
        self._free_tiers[provider] = FreeTierStatus(
            provider=provider,
            daily_credits=daily_credits,
            monthly_credits=monthly_credits,
        )

    def recommend_provider(self, content_type: str, quality: str) -> str:
        """Recommend cheapest provider based on free-tier availability."""
        recommendations = {
            "music": {"free": "ace_step", "standard": "ace_step", "high": "suno_api"},
            "podcast": {"free": "edge_tts", "standard": "kokoro", "high": "google_tts"},
            "video": {"free": "ken_burns", "standard": "seedance", "high": "kling"},
        }
        type_recs = recommendations.get(content_type, {})
        recommended = type_recs.get(quality, "ken_burns")
        if recommended in self._free_tiers:
            tier = self._free_tiers[recommended]
            if tier.daily_remaining == 0:
                fallbacks = {"suno_api": "ace_step", "ace_step": "suno_api", "kokoro": "edge_tts",
                             "edge_tts": "kokoro", "google_tts": "kokoro", "kling": "seedance",
                             "seedance": "ken_burns"}
                return fallbacks.get(recommended, "ken_burns")
        return recommended

    def get_total_costs(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for entry in self._costs:
            totals[entry.provider] = totals.get(entry.provider, 0) + entry.estimated_cents
        return totals

    def get_weekly_costs(self) -> int:
        return sum(entry.estimated_cents for entry in self._costs)

    def get_content_costs(self, content_type: str) -> int:
        return sum(entry.estimated_cents for entry in self._costs if entry.content_type == content_type)
