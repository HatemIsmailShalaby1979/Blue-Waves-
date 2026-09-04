from __future__ import annotations

import uuid
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .dialogue import build_narration
from .governance import Governance
from .models import AssetStatus, ContentAsset, Language, now_iso
from .providers import ProviderHealthMonitor, ProviderRegistry, ProviderUnavailable
from .video_use_editor import VideoUseEditor


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
        self._video_use_enabled = getattr(settings, "video_use_enabled", True)
        self._video_use_editor: VideoUseEditor | None = None
        if self._video_use_enabled:
            try:
                self._video_use_editor = VideoUseEditor(settings)
            except Exception:
                self._video_use_editor = None

    def generate(self, topic: str, prompt: str, duration: int = 5,
                 resolution: str | None = None, quality: str = "high",
                 preferred_provider: str | None = None,
                 narration: str | None = None, music_mode: str = "ambient") -> VideoGenerationResult:
        # Best quality means 1080p. Previously every render was pinned to 720p,
        # so "high" produced the same output as "draft".
        if not resolution:
            resolution = "1080p" if quality in ("high", "premium") else "720p"

        # Videos are always narrated in English. When no narration is supplied,
        # build one from the topic sized to the requested runtime so the topic is
        # actually covered instead of being repeated or cut off mid-sentence.
        if not (narration or "").strip():
            narration = build_narration(topic, duration)

        asset_id = f"video-{uuid.uuid4().hex[:12]}"
        asset = ContentAsset(
            asset_id=asset_id,
            tenant_id=self._settings.tenant_id,
            topic=topic,
            pillar="education",
            language=Language.EN,
            status=AssetStatus.PRODUCED,
        )

        providers = self._provider_candidates(preferred_provider, quality)
        errors: list[str] = []
        for provider in providers:
          reservation = None
          try:
            if self._providers:
                reservation = self._providers.rotation.reserve(
                    provider.name,
                    monthly_budget_cents=self._settings.monthly_cloud_cents,
                )
                if reservation is None:
                    errors.append(f"{provider.name}: quota or budget unavailable")
                    continue
            # Ken Burns provider supports narration and music_mode
            if provider.name == "ken_burns":
                video_bytes = provider.generate(
                    prompt=prompt, duration=duration, resolution=resolution,
                    narration=narration, music_mode=music_mode
                )
            else:
                video_bytes = provider.generate(prompt=prompt, duration=duration, resolution=resolution)
            video_path = str(Path(self._settings.data_dir) / "videos" / f"{asset_id}.mp4")
            Path(video_path).parent.mkdir(parents=True, exist_ok=True)
            Path(video_path).write_bytes(video_bytes)

            # Post-production via video-use: overlays, transitions, color grading,
            # captioning, YouTube-spec encoding. This bridges the quality gap
            # between "raw render" and "real YouTube video".
            if self._video_use_editor:
                try:
                    edit_result = self._video_use_editor.edit(
                        raw_video_path=Path(video_path),
                        transcript_text=narration or prompt,
                        narration_audio_path=None,
                        topic=topic,
                        duration=duration,
                        width=1920 if quality in ("high", "premium") else 1280,
                        height=1080 if quality in ("high", "premium") else 720,
                    )
                    if edit_result.success and edit_result.output_path:
                        # Replace raw video with post-produced version.
                        # shutil.move survives cross-drive temp dirs where rename fails;
                        # the raw file is only removed after the move succeeds.
                        import shutil
                        tmp_out = Path(edit_result.output_path)
                        raw = Path(video_path)
                        backup = raw.with_name(raw.stem + ".raw" + raw.suffix)
                        raw.replace(backup)
                        try:
                            shutil.move(str(tmp_out), str(raw))
                        except Exception:
                            backup.replace(raw)
                            raise
                        backup.unlink(missing_ok=True)
                        asset.metadata["video_use"] = {
                            "transcript": edit_result.transcript[:500],
                            "edl_entries": len(edit_result.edl),
                            "self_eval_score": edit_result.self_eval_score,
                            "issues": edit_result.issues[:5],
                        }
                except Exception as exc:
                    # Post-production failure is not fatal — raw video is still usable
                    asset.metadata["video_use_error"] = str(exc)[:200]

            asset.media_manifest = {"video_path": video_path, "provider": provider.name, "provider_attempts": [p.name for p in providers], "duration": duration, "resolution": resolution}
            asset.transition(AssetStatus.AWAITING_OWNER)
            self._health.record_success(provider.name)
            return VideoGenerationResult(
                success=True,
                asset=asset,
                video_path=video_path,
                provider_used=provider.name,
            )
          except Exception as exc:
            if reservation is not None and self._providers:
                self._providers.rotation.release(reservation)
            self._health.record_failure(provider.name, str(exc))
            errors.append(f"{provider.name}: {exc}")
        asset.transition(AssetStatus.REJECTED)
        return VideoGenerationResult(success=False, asset=asset, error="; ".join(errors))

    def _provider_candidates(self, preferred_provider: str | None, quality: str) -> list[Any]:
        if self._providers:
            preferred = preferred_provider if preferred_provider else ("kling" if quality in ("high", "premium") else "seedance" if quality == "standard" else "ken_burns")
            return self._providers.configured_media_candidates("video", preferred, quality)
        return [self._select_video_provider(preferred_provider or self._select_provider(quality))]

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
