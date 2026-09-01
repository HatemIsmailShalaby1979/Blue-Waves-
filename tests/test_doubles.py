from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from blue_waves.models import now_iso


class InMemoryMusicProvider:
    """Contract-test double for music generation. No network, no GPU."""

    def __init__(self) -> None:
        self.name = "in_memory_music"
        self.generated: list[dict[str, Any]] = []

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        self.generated.append({"prompt": prompt, "duration": duration, "genre": genre, "mood": mood})
        return b"fake-wav-audio-bytes"


class InMemoryTTSProvider:
    """Contract-test double for TTS. Returns silence bytes."""

    def __init__(self) -> None:
        self.name = "in_memory_tts"
        self.generated: list[dict[str, Any]] = []

    def generate(self, text: str, voice_id: str = "default", **kwargs: Any) -> bytes:
        self.generated.append({"text": text, "voice": voice_id})
        return b"fake-tts-audio-bytes"


class InMemoryVideoProvider:
    """Contract-test double for video generation."""

    def __init__(self) -> None:
        self.name = "in_memory_video"
        self.generated: list[dict[str, Any]] = []

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 **kwargs: Any) -> bytes:
        self.generated.append({"prompt": prompt, "duration": duration, "resolution": resolution})
        return b"fake-video-bytes"


class InMemoryFinanceEngine:
    """Contract-test double for SHIPO. Tracks calls without persistence."""

    def __init__(self) -> None:
        self.costs: list[dict[str, Any]] = []
        self.free_tiers: dict[str, dict[str, Any]] = {}

    def log_cost(self, provider: str, content_type: str, asset_id: str,
                 credits: int, estimated_cents: int) -> None:
        self.costs.append({"provider": provider, "asset_id": asset_id, "cents": estimated_cents})

    def get_remaining_free_tier(self, provider: str) -> dict[str, Any]:
        return self.free_tiers.get(provider, {"daily_credits": -1, "monthly_credits": -1})

    def recommend_provider(self, content_type: str, quality: str) -> str:
        return "in_memory_provider"


class InMemoryContentQueue:
    """Contract-test double for content queue."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def add(self, request: Any) -> None:
        self.requests.append(request)

    def get_by_stage(self, stage: str) -> list[Any]:
        return [r for r in self.requests if getattr(r, "stage", None) == stage]

    def get_weekly_count(self, content_type: str) -> int:
        return 0

    def size(self) -> int:
        return len(self.requests)


class InMemoryProviderHealth:
    """Contract-test double for provider health monitoring."""

    def __init__(self) -> None:
        self.health: dict[str, dict[str, Any]] = {}

    def record_success(self, provider: str) -> None:
        if provider not in self.health:
            self.health[provider] = {"status": "healthy", "successes": 0, "failures": 0}
        self.health[provider]["successes"] += 1

    def record_failure(self, provider: str, error: str) -> None:
        if provider not in self.health:
            self.health[provider] = {"status": "healthy", "successes": 0, "failures": 0}
        self.health[provider]["failures"] += 1
        self.health[provider]["status"] = "degraded"

    def is_healthy(self, provider: str) -> bool:
        if provider not in self.health:
            return True
        return self.health[provider]["status"] == "healthy"

    def get_fallback(self, primary_provider: str) -> str:
        fallbacks = {
            "kling": "seedance",
            "seedance": "hailuo",
            "suno_api": "ace_step",
            "kokoro": "edge_tts",
            "google_tts": "edge_tts",
        }
        return fallbacks.get(primary_provider, "ken_burns")

    def get_status(self) -> dict[str, dict[str, Any]]:
        return dict(self.health)
