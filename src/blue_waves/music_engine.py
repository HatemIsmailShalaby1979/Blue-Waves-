from __future__ import annotations

import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .governance import Governance
from .models import AssetStatus, MusicAsset, now_iso
from .providers import ProviderHealthMonitor, ProviderRegistry, ProviderUnavailable


@dataclass
class MusicGenerationResult:
    success: bool
    asset: MusicAsset | None = None
    audio_path: str | None = None
    provider_used: str = ""
    error: str | None = None


class MusicEngine:
    """BELAL — music composition engine with provider fallback."""

    def __init__(self, settings: Settings, governance: Governance,
                 provider_registry: ProviderRegistry | None = None,
                 health_monitor: ProviderHealthMonitor | None = None) -> None:
        self._settings = settings
        self._governance = governance
        self._providers = provider_registry
        self._health = health_monitor or ProviderHealthMonitor()

    def generate(self, topic: str, genre: str = "cinematic", mood: str = "inspirational",
                 duration_seconds: int = 180, lyrics: str = "",
                 preferred_provider: str = "ace_step", quality: str = "high") -> MusicGenerationResult:
        asset_id = f"music-{uuid.uuid4().hex[:12]}"
        asset = MusicAsset(
            asset_id=asset_id,
            tenant_id=self._settings.tenant_id,
            title=f"Music for {topic}",
            genre=genre,
            mood=mood,
            duration_seconds=duration_seconds,
            language="en",
            prompt=f"{topic} - {genre} - {mood}",
            lyrics=lyrics,
            provider=preferred_provider,
            quality=quality,
            media_manifest={},
        )
        asset.transition(AssetStatus.COMPOSING)

        provider = self._select_provider(preferred_provider)
        try:
            audio_bytes = provider.generate(
                prompt=asset.prompt,
                lyrics=lyrics,
                duration=duration_seconds,
                genre=genre,
                mood=mood,
            )
            audio_path = str(Path(self._settings.data_dir) / "music" / f"{asset_id}.wav")
            Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
            Path(audio_path).write_bytes(audio_bytes)
            asset.provider = provider.name
            asset.audio_path = audio_path
            asset.transition(AssetStatus.MIXING)
            asset.transition(AssetStatus.AWAITING_OWNER)
            self._health.record_success(provider.name)
            return MusicGenerationResult(
                success=True,
                asset=asset,
                audio_path=audio_path,
                provider_used=provider.name,
            )
        except (ProviderUnavailable, Exception) as exc:
            self._health.record_failure(provider.name, str(exc))
            fallback_name = "local_audio_fallback"
            try:
                fallback = self._select_provider(fallback_name)
                audio_bytes = fallback.generate(
                    prompt=asset.prompt,
                    lyrics=lyrics,
                    duration=duration_seconds,
                    genre=genre,
                    mood=mood,
                )
                audio_path = str(Path(self._settings.data_dir) / "music" / f"{asset_id}.wav")
                Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
                Path(audio_path).write_bytes(audio_bytes)
                asset.audio_path = audio_path
                asset.provider = fallback.name
                asset.transition(AssetStatus.MIXING)
                asset.transition(AssetStatus.AWAITING_OWNER)
                self._health.record_success(fallback.name)
                return MusicGenerationResult(
                    success=True,
                    asset=asset,
                    audio_path=audio_path,
                    provider_used=fallback.name,
                )
            except Exception as fallback_exc:
                self._health.record_failure(fallback_name, str(fallback_exc))
                asset.transition(AssetStatus.REJECTED)
                return MusicGenerationResult(
                    success=False,
                    asset=asset,
                    error=f"primary: {exc}, fallback: {fallback_exc}",
                )

    def _select_provider(self, provider_name: str) -> Any:
        if self._providers:
            try:
                return self._providers.get_music_provider(provider_name)
            except ProviderUnavailable:
                return self._providers.get_music_provider("local_audio_fallback")
        from .providers import ACEStepMusicProvider
        return ACEStepMusicProvider()

    def compose_multiple(self, prompts: list[dict[str, Any]]) -> list[MusicGenerationResult]:
        results = []
        for prompt_data in prompts:
            result = self.generate(
                topic=prompt_data.get("topic", "unknown"),
                genre=prompt_data.get("genre", "cinematic"),
                mood=prompt_data.get("mood", "inspirational"),
                duration_seconds=prompt_data.get("duration_seconds", 180),
                lyrics=prompt_data.get("lyrics", ""),
                preferred_provider=prompt_data.get("provider", "ace_step"),
                quality=prompt_data.get("quality", "high"),
            )
            results.append(result)
        return results
