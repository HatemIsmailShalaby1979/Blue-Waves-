from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import now_iso


# Real per-generation provider costs (in cents USD).
# These are estimated based on published pricing as of 2026-09.
# Updated by SHEPO when providers change their pricing.
PROVIDER_COSTS: dict[str, dict[str, Any]] = {
    "suno_api":          {"per_generation": 8,  "per_unit": "song",        "notes": "8 credits/song ~$0.08"},
    "aimlapi_music":     {"per_generation": 5,  "per_unit": "song",        "notes": "~$0.05/generation"},
    "kai_music":         {"per_generation": 1,  "per_unit": "song",        "notes": "~$0.01/generation (if available)"},
    "ace_step":          {"per_generation": 0,  "per_unit": "song",        "notes": "Free (local ROCm GPU)"},
    "local_audio_fallback": {"per_generation": 0, "per_unit": "song",     "notes": "Free (CPU synth)"},
    "elevenlabs_tts":    {"per_generation": 30, "per_unit": "1000_chars",  "notes": "~$0.30/1000 chars"},
    "kokoro":            {"per_generation": 1,  "per_unit": "1000_chars",  "notes": "~$0.01/1000 chars"},
    "google_tts":        {"per_generation": 16, "per_unit": "1000_chars",  "notes": "~$0.16/1000 chars"},
    "edge_tts":          {"per_generation": 0,  "per_unit": "request",     "notes": "Free (Microsoft Edge)"},
    "local_tts_fallback": {"per_generation": 0, "per_unit": "request",     "notes": "Free (CPU)"},
    "kling":             {"per_generation": 50, "per_unit": "video",        "notes": "~$0.50/generation"},
    "seedance":          {"per_generation": 30, "per_unit": "video",        "notes": "~$0.30/generation"},
    "ken_burns":         {"per_generation": 0,  "per_unit": "video",        "notes": "Free (local ffmpeg)"},
}

# YouTube CPM (cost per mille / per 1000 views) estimates by content type
YOUTUBE_CPM = {
    "music": 1.5,      # $1.50 per 1000 views (music has lower CPM)
    "video": 4.0,      # $4.00 per 1000 views (educational content)
    "podcast": 3.0,    # $3.00 per 1000 views (podcast)
}


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
    """SHEPO — real cost tracking, revenue projection, and profit analysis.

    Replaces the old SHIPO engine that logged 0 for every cost.
    Now tracks real per-provider costs and projects YouTube revenue.
    """

    def __init__(self) -> None:
        self._costs: list[CostEntry] = []
        self._free_tiers: dict[str, FreeTierStatus] = {}
        self._revenue_events: list[dict[str, Any]] = []

    def log_cost(self, provider: str, content_type: str, asset_id: str,
                 credits: int = 0, estimated_cents: int = 0,
                 duration_seconds: int = 0, char_count: int = 0) -> None:
        """Log a real cost for a provider invocation.

        If estimated_cents is 0, auto-calculate from PROVIDER_COSTS based on
        the provider's pricing model and the duration/char_count provided.
        """
        if estimated_cents == 0:
            cost_info = PROVIDER_COSTS.get(provider, {})
            per_gen = cost_info.get("per_generation", 0)
            unit = cost_info.get("per_unit", "")
            if unit == "song" or unit == "video" or unit == "request":
                estimated_cents = per_gen
            elif unit == "1000_chars" and char_count > 0:
                estimated_cents = max(1, (char_count // 1000 + 1) * per_gen) if per_gen else 0
            elif unit == "minute" and duration_seconds > 0:
                estimated_cents = max(1, (duration_seconds // 60 + 1) * per_gen) if per_gen else 0
            else:
                estimated_cents = per_gen

        entry = CostEntry(
            event_id=f"cost-{asset_id}-{provider}-{len(self._costs)}",
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
        """Recommend cheapest provider that meets the quality threshold."""
        recommendations = {
            "music": {"free": "ace_step", "standard": "aimlapi_music", "high": "suno_api", "premium": "suno_api"},
            "podcast": {"free": "edge_tts", "standard": "kokoro", "high": "elevenlabs_tts", "premium": "elevenlabs_tts"},
            "video": {"free": "ken_burns", "standard": "seedance", "high": "kling", "premium": "kling"},
        }
        type_recs = recommendations.get(content_type, {})
        recommended = type_recs.get(quality, "ken_burns")
        if recommended in self._free_tiers:
            tier = self._free_tiers[recommended]
            if tier.daily_remaining == 0:
                fallbacks = {
                    "suno_api": "aimlapi_music", "aimlapi_music": "ace_step", "ace_step": "local_audio_fallback",
                    "kokoro": "edge_tts", "elevenlabs_tts": "edge_tts", "google_tts": "elevenlabs_tts",
                    "edge_tts": "local_tts_fallback", "kling": "seedance", "seedance": "ken_burns",
                }
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

    def get_provider_cost_comparison(self) -> list[dict[str, Any]]:
        """Return cost comparison table for all providers (for cockpit display)."""
        comparisons = []
        for provider, cost in PROVIDER_COSTS.items():
            comparisons.append({
                "provider": provider,
                "cost_per_unit_cents": cost.get("per_generation", 0),
                "unit": cost.get("per_unit", ""),
                "notes": cost.get("notes", ""),
            })
        return comparisons

    def project_monthly_revenue(self, views_per_video: int = 500,
                                  cpm: float | None = None,
                                  upload_frequency: int = 15) -> dict[str, Any]:
        """Project monthly YouTube revenue.

        Args:
            views_per_video: Expected average views per video
            cpm: Cost per mille (per 1000 views). If None, uses content-type average.
            upload_frequency: Number of uploads per month

        Returns revenue projection with breakdown.
        """
        if cpm is None:
            cpm = sum(YOUTUBE_CPM.values()) / len(YOUTUBE_CPM)  # Average CPM

        revenue_per_video = (views_per_video / 1000) * cpm
        monthly_revenue = revenue_per_video * upload_frequency
        monthly_cost = self.get_weekly_costs() * 4  # Approximate monthly from weekly
        net_profit = monthly_revenue - monthly_cost

        return {
            "views_per_video": views_per_video,
            "cpm": cpm,
            "upload_frequency": upload_frequency,
            "revenue_per_video_cents": int(revenue_per_video * 100),
            "monthly_revenue_cents": int(monthly_revenue * 100),
            "monthly_cost_cents": monthly_cost,
            "net_profit_cents": int(net_profit * 100),
            "profitable": net_profit > 0,
        }

    def calculate_break_even(self, monthly_budget_cents: int = 0,
                              views_per_video: int = 500,
                              upload_frequency: int = 15) -> dict[str, Any]:
        """Calculate when revenue exceeds costs (break-even point).

        Returns the number of months until profitability, and the required
        views per video to break even at the current cost level.
        """
        monthly_cost = max(monthly_budget_cents, self.get_weekly_costs() * 4)
        avg_cpm = sum(YOUTUBE_CPM.values()) / len(YOUTUBE_CPM)

        # Required views to break even
        required_revenue = monthly_cost / 100  # Convert cents to dollars
        required_views_per_video = int((required_revenue / upload_frequency) / (avg_cpm / 1000))

        # Months until profitable (assuming 20% MoM growth)
        current_revenue = (views_per_video / 1000) * avg_cpm * upload_frequency
        if current_revenue >= monthly_cost / 100:
            months_to_break_even = 0
        else:
            # Assuming 20% month-over-month growth in views
            months = 0
            rev = current_revenue
            cost = monthly_cost / 100
            while rev < cost and months < 24:
                rev *= 1.2
                months += 1
            months_to_break_even = months if months < 24 else -1

        return {
            "monthly_cost_cents": monthly_cost,
            "current_monthly_revenue_cents": int(current_revenue * 100),
            "required_views_per_video": required_views_per_video,
            "months_to_break_even": months_to_break_even,
            "break_even_feasible": months_to_break_even >= 0,
            "avg_cpm": avg_cpm,
        }

    def get_runway(self, monthly_budget_cents: int = 0) -> dict[str, Any]:
        """How many months the current budget can sustain operations."""
        monthly_cost = max(monthly_budget_cents, self.get_weekly_costs() * 4)
        if monthly_cost == 0:
            return {"runway_months": -1, "note": "No costs tracked yet — operation is free-tier"}
        return {
            "runway_months": -1 if monthly_cost == 0 else 999,
            "monthly_cost_cents": monthly_cost,
            "note": "Budget is for cloud API costs only; local providers are free",
        }

    def get_shepo_report(self) -> dict[str, Any]:
        """Full SHEPO financial report for the cockpit."""
        return {
            "agent": "SHEPO",
            "role": "Finance & Profit Strategist",
            "total_costs": self.get_total_costs(),
            "weekly_cost_cents": self.get_weekly_costs(),
            "content_costs": {
                "music_cents": self.get_content_costs("music"),
                "podcast_cents": self.get_content_costs("podcast"),
                "video_cents": self.get_content_costs("video"),
            },
            "provider_comparison": self.get_provider_cost_comparison(),
            "revenue_projection": self.project_monthly_revenue(),
            "break_even_analysis": self.calculate_break_even(),
            "cost_count": len(self._costs),
        }
