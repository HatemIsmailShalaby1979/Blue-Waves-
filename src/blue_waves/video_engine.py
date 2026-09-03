from __future__ import annotations

import uuid
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .governance import Governance
from .models import AssetStatus, ContentAsset, Language, now_iso
from .providers import ProviderHealthMonitor, ProviderRegistry, ProviderUnavailable


@dataclass
class VideoGenerationResult:
    success: bool
    asset: ContentAsset | None = None
    video_path: str | None = None
    provider_used: str = ""
    error: str | None = None


class VideoEngine:
    """Video generation engine with quality-aware provider routing."""

    def __init__(self, settings: Settings, governance: Governance,
                 provider_registry: ProviderRegistry | None = None,
                 health_monitor: ProviderHealthMonitor | None = None) -> None:
        self._settings = settings
        self._governance = governance
        self._providers = provider_registry
        self._health = health_monitor or ProviderHealthMonitor()

    def generate(self, topic: str, prompt: str, duration: int = 5,
                 resolution: str = "720p", quality: str = "high",
                 preferred_provider: str | None = None) -> VideoGenerationResult:
        asset_id = f"video-{uuid.uuid4().hex[:12]}"
        asset = ContentAsset(
            asset_id=asset_id,
            tenant_id=self._settings.tenant_id,
            topic=topic,
            pillar="education",
            language=Language.EN,
            status=AssetStatus.PRODUCED,
        )

        provider_name = preferred_provider or self._select_provider(quality)
        provider = self._select_video_provider(provider_name)

        try:
            video_bytes = provider.generate(prompt=prompt, duration=duration, resolution=resolution)
            video_path = str(Path(self._settings.data_dir) / "videos" / f"{asset_id}.mp4")
            Path(video_path).parent.mkdir(parents=True, exist_ok=True)
            Path(video_path).write_bytes(video_bytes)
            asset.media_manifest = {"video_path": video_path, "provider": provider.name}
            asset.transition(AssetStatus.AWAITING_OWNER)
            self._health.record_success(provider.name)
            return VideoGenerationResult(
                success=True,
                asset=asset,
                video_path=video_path,
                provider_used=provider.name,
            )
        except (ProviderUnavailable, Exception) as exc:
            self._health.record_failure(provider.name, str(exc))
            fallback_name = "ken_burns"
            try:
                fallback = self._select_video_provider(fallback_name)
                video_bytes = fallback.generate(prompt=prompt, duration=duration, resolution=resolution)
                video_path = str(Path(self._settings.data_dir) / "videos" / f"{asset_id}.mp4")
                Path(video_path).parent.mkdir(parents=True, exist_ok=True)
                Path(video_path).write_bytes(video_bytes)
                asset.media_manifest = {"video_path": video_path, "provider": fallback.name}
                asset.transition(AssetStatus.AWAITING_OWNER)
                self._health.record_success(fallback.name)
                return VideoGenerationResult(
                    success=True,
                    asset=asset,
                    video_path=video_path,
                    provider_used=fallback.name,
                )
            except Exception as fallback_exc:
                self._health.record_failure(fallback_name, str(fallback_exc))
                return VideoGenerationResult(
                    success=False,
                    asset=asset,
                    error=f"primary: {exc}, fallback: {fallback_exc}",
                )

    def _select_provider(self, quality: str) -> str:
        quality_map = {
            "draft": "ken_burns",
            "standard": "seedance",
            "high": "kling",
            "premium": "kling",
        }
        return quality_map.get(quality, "ken_burns")

    def _select_video_provider(self, name: str) -> Any:
        if self._providers:
            try:
                return self._providers.get_video_provider(name)
            except ProviderUnavailable:
                return self._providers.get_video_provider("ken_burns")
        # A bare engine has no configured provider registry; retain the v0.1
        # contract-test behavior and fail closed. The application supplies the
        # registry, including the working local FFmpeg fallback.
        from .providers import DeferredMotionProvider
        return DeferredMotionProvider()

    def generate_slideshow(self, topic: str, slides: list[str], duration_per_slide: int = 5) -> VideoGenerationResult:
        prompt = f"educational slideshow about {topic} with slides: {', '.join(slides)}"
        return self.generate(
            topic=topic,
            prompt=prompt,
            duration=duration_per_slide * len(slides),
            resolution="720p",
            quality="draft",
            preferred_provider="ken_burns",
        )

    def generate_kinetic(self, topic: str, prompt: str, duration: int = 10) -> VideoGenerationResult:
        return self.generate(
            topic=topic,
            prompt=prompt,
            duration=duration,
            resolution="1080p",
            quality="high",
        )
