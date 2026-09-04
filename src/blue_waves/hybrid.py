from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .compat import StrEnum
from .governance import Governance, GovernanceViolation
from .providers import OpenAICompatibleProvider, ProviderUnavailable


class Stage(StrEnum):
    LESSON_DRAFT = "lesson_draft"
    BILINGUAL_REVIEW = "bilingual_review"
    STILL_IMAGES = "still_images"
    MOTION = "motion"
    TTS = "tts"
    MUSIC = "music"
    ASSEMBLY = "assembly"
    DEEP_REVIEW = "deep_review"
    MUSIC_COMPOSITION = "music_composition"
    MUSIC_MIXING = "music_mixing"
    PODCAST_SCRIPT = "podcast_script"
    PODCAST_VOICE = "podcast_voice"
    PODCAST_MIX = "podcast_mix"
    VIDEO_GENERATION = "video_generation"
    VIDEO_RENDER = "video_render"


@dataclass(frozen=True)
class Route:
    stage: Stage
    mode: str
    provider: str
    reason: str
    cost_ceiling_required: int = 0


class HybridRouter:
    """Central compute policy: local first, cloud only where quality requires it."""

    def __init__(self, governance: Governance, local: OpenAICompatibleProvider,
                 cloud: OpenAICompatibleProvider | None = None,
                 clouds: list[OpenAICompatibleProvider] | None = None):
        self.governance = governance
        self.local = local
        self.cloud = cloud
        self.clouds = list(clouds or ([] if cloud is None else [cloud]))

    def route(self, stage: Stage, cloud_requested: bool = False) -> Route:
        if stage is Stage.MOTION:
            cloud = next((candidate for candidate in self.clouds if candidate.configured), None)
            if cloud is None:
                return Route(stage, "local_fallback", "ffmpeg", "no verified motion provider; use Ken Burns/slides")
            if self.governance.policy.monthly_cloud_cents <= 0:
                return Route(stage, "local_fallback", "ffmpeg", "cloud budget is zero; use Ken Burns/slides")
            return Route(stage, "cloud", cloud.name, "local GPU cannot generate useful motion at cadence", 1)
        if stage in (Stage.BILINGUAL_REVIEW, Stage.DEEP_REVIEW) and cloud_requested:
            cloud = next((candidate for candidate in self.clouds if candidate.configured), None)
            if cloud is None:
                return Route(stage, "local", self.local.name, "cloud requested but no configured provider; preserve work locally")
            if self.governance.policy.monthly_cloud_cents <= 0:
                return Route(stage, "local", self.local.name, "cloud budget is zero; local model remains the default")
            return Route(stage, "cloud", cloud.name, "quality-critical language/reasoning escalation", 1)
        if stage in (Stage.STILL_IMAGES, Stage.TTS, Stage.MUSIC, Stage.ASSEMBLY):
            return Route(stage, "local", "local_media_tools", "available on the workstation or Linux rendering box")
        return Route(stage, "local", self.local.name, "local-first default")

    def assert_route_is_allowed(self, route: Route) -> None:
        if route.mode == "cloud" and route.cost_ceiling_required > self.governance.policy.monthly_cloud_cents:
            raise GovernanceViolation("hybrid route exceeds the monthly cloud ceiling")

    def route_music(self, quality: str = "high", preferred_provider: str | None = None) -> Route:
        if quality == "free":
            return Route(Stage.MUSIC, "local", "ace_step", "free tier maximization")
        if quality == "standard":
            return Route(Stage.MUSIC, "local", "ace_step", "standard quality via local GPU")
        return Route(Stage.MUSIC, "cloud", preferred_provider or "suno_api", "high quality cloud generation", 5)

    def route_podcast(self, quality: str = "high", preferred_tts: str | None = None) -> Route:
        if quality == "free":
            return Route(Stage.TTS, "local", "edge_tts", "free TTS provider")
        if quality == "standard":
            return Route(Stage.TTS, "local", "kokoro", "standard quality TTS")
        return Route(Stage.TTS, "cloud", preferred_tts or "google_tts", "high quality cloud TTS", 3)

    def route_video(self, quality: str = "high", preferred_provider: str | None = None) -> Route:
        if quality == "draft":
            return Route(Stage.MOTION, "local", "ken_burns", "draft quality Ken Burns")
        if quality == "standard":
            return Route(Stage.MOTION, "cloud", preferred_provider or "seedance", "standard quality video", 10)
        return Route(Stage.MOTION, "cloud", preferred_provider or "kling", "high quality video generation", 20)
