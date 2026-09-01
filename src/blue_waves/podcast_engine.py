from __future__ import annotations

import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .governance import Governance
from .models import AssetStatus, PodcastAsset, now_iso
from .providers import ProviderHealthMonitor, ProviderRegistry, ProviderUnavailable


@dataclass
class PodcastGenerationResult:
    success: bool
    asset: PodcastAsset | None = None
    audio_path: str | None = None
    tts_provider_used: str = ""
    music_provider_used: str = ""
    error: str | None = None


class PodcastEngine:
    """ZACK — multi-host podcast engine with TTS + music mixing."""

    def __init__(self, settings: Settings, governance: Governance,
                 provider_registry: ProviderRegistry | None = None,
                 health_monitor: ProviderHealthMonitor | None = None) -> None:
        self._settings = settings
        self._governance = governance
        self._providers = provider_registry
        self._health = health_monitor or ProviderHealthMonitor()

    def generate(self, topic: str, script: str, host_voice: str = "en-US-AriaNeural",
                 guest_voice: str | None = None, duration_seconds: int = 1800,
                 format: str = "dialogue", music_intro: bool = True,
                 music_outro: bool = True, quality: str = "high") -> PodcastGenerationResult:
        asset_id = f"podcast-{uuid.uuid4().hex[:12]}"
        asset = PodcastAsset(
            asset_id=asset_id,
            tenant_id=self._settings.tenant_id,
            title=f"Podcast: {topic}",
            topic=topic,
            host_voice=host_voice,
            guest_voice=guest_voice,
            language="en",
            duration_target_seconds=duration_seconds,
            format=format,
            script=script,
        )
        asset.transition(AssetStatus.SCRIPTED)

        tts_provider = self._select_tts_provider()
        try:
            host_audio = tts_provider.generate(text=script, voice_id=host_voice)
            asset.transition(AssetStatus.VOICE_RECORDING)
            self._health.record_success(tts_provider.name)
        except (ProviderUnavailable, Exception) as exc:
            self._health.record_failure(tts_provider.name, str(exc))
            fallback_name = "local_tts_fallback"
            try:
                tts_provider = self._select_tts_provider(fallback_name)
                host_audio = tts_provider.generate(text=script, voice_id=host_voice)
                asset.transition(AssetStatus.VOICE_RECORDING)
                asset.tts_provider = fallback_name
                self._health.record_success(fallback_name)
            except Exception as fallback_exc:
                self._health.record_failure(fallback_name, str(fallback_exc))
                asset.transition(AssetStatus.REJECTED)
                return PodcastGenerationResult(
                    success=False,
                    asset=asset,
                    error=f"tts primary: {exc}, fallback: {fallback_exc}",
                )

        music_intro_path = None
        music_outro_path = None
        if music_intro or music_outro:
            music_provider = self._select_music_provider()
            try:
                if music_intro:
                    music_intro_audio = music_provider.generate(
                        prompt=f"podcast intro for {topic}",
                        duration=30,
                    )
                    music_intro_path = str(Path(self._settings.data_dir) / "podcasts" / f"{asset_id}-intro.wav")
                    Path(music_intro_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(music_intro_path).write_bytes(music_intro_audio)
                if music_outro:
                    music_outro_audio = music_provider.generate(
                        prompt=f"podcast outro for {topic}",
                        duration=30,
                    )
                    music_outro_path = str(Path(self._settings.data_dir) / "podcasts" / f"{asset_id}-outro.wav")
                    Path(music_outro_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(music_outro_path).write_bytes(music_outro_audio)
                asset.music_provider = music_provider.name
                self._health.record_success(music_provider.name)
            except (ProviderUnavailable, Exception) as exc:
                self._health.record_failure(music_provider.name, str(exc))

        audio_path = str(Path(self._settings.data_dir) / "podcasts" / f"{asset_id}.wav")
        Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).write_bytes(host_audio)
        asset.audio_path = audio_path
        asset.music_intro_path = music_intro_path
        asset.music_outro_path = music_outro_path
        asset.transition(AssetStatus.MIXING)
        asset.transition(AssetStatus.AWAITING_OWNER)

        return PodcastGenerationResult(
            success=True,
            asset=asset,
            audio_path=audio_path,
            tts_provider_used=asset.tts_provider,
            music_provider_used=asset.music_provider,
        )

    def _select_tts_provider(self, name: str | None = None) -> Any:
        provider_name = name or self._settings.kokoro_api_key and "kokoro" or "edge_tts"
        if self._providers:
            return self._providers.get_tts_provider(provider_name)
        from .providers import EdgeTTSProvider
        return EdgeTTSProvider()

    def _select_music_provider(self, name: str | None = None) -> Any:
        provider_name = name or self._settings.ace_step_bin and "ace_step" or "ace_step"
        if self._providers:
            try:
                return self._providers.get_music_provider(provider_name)
            except ProviderUnavailable:
                return self._providers.get_music_provider("local_audio_fallback")
        from .providers import ACEStepMusicProvider
        return ACEStepMusicProvider()

    def generate_solo(self, topic: str, script: str, voice: str = "en-US-AriaNeural",
                      duration_seconds: int = 600) -> PodcastGenerationResult:
        return self.generate(
            topic=topic,
            script=script,
            host_voice=voice,
            duration_seconds=duration_seconds,
            format="solo",
            music_intro=True,
            music_outro=True,
        )

    def generate_dialogue(self, topic: str, host_script: str, guest_script: str,
                          host_voice: str = "en-US-AriaNeural",
                          guest_voice: str = "en-US-GuyNeural",
                          duration_seconds: int = 1800) -> PodcastGenerationResult:
        full_script = f"[HOST]: {host_script}\n\n[GUEST]: {guest_script}"
        return self.generate(
            topic=topic,
            script=full_script,
            host_voice=host_voice,
            guest_voice=guest_voice,
            duration_seconds=duration_seconds,
            format="dialogue",
        )
