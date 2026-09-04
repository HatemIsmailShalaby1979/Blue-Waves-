from __future__ import annotations

import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .governance import Governance
from .models import AssetStatus, MusicAsset, now_iso
from .providers import ProviderHealthMonitor, ProviderRegistry, ProviderUnavailable, AimlapiMusicProvider, KaiMusicProvider


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
                 preferred_provider: str = "suno_api", quality: str = "high") -> MusicGenerationResult:
        # Enforce minimum 180s for high/premium quality — competitive tracks
        # need to be full-length, not ringtones.
        if quality in ("high", "premium") and duration_seconds < 180:
            duration_seconds = 180

        # Auto-generate lyrics if none provided — full songs need structure.
        if not lyrics:
            lyrics = self._generate_lyrics(topic, genre, mood)

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

        providers = self._provider_candidates(preferred_provider, quality)
        errors: list[str] = []
        if not providers:
            asset.transition(AssetStatus.REJECTED)
            return MusicGenerationResult(
                success=False, asset=asset,
                error=("local pixel generation is disabled (BLUE_WAVES_ALLOW_LOCAL_FALLBACK=false) "
                       "and no cloud music provider is configured — add a funded aimlapi key or upload an MP3"),
            )
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
            asset.metadata["provider_attempts"] = [p.name for p in providers]
            if reservation is not None:
                asset.metadata["quota_reservation"] = reservation.token
            return MusicGenerationResult(
                success=True,
                asset=asset,
                audio_path=audio_path,
                provider_used=provider.name,
            )
          except Exception as exc:
            if reservation is not None and self._providers:
                self._providers.rotation.release(reservation)
            self._health.record_failure(provider.name, str(exc))
            errors.append(f"{provider.name}: {exc}")
        asset.transition(AssetStatus.REJECTED)
        return MusicGenerationResult(success=False, asset=asset, error="; ".join(errors))

    #: Local PCM synth is never acceptable for paid-tier quality — a silent
    #: downgrade to noise is worse than an honest, actionable failure.
    #: Strict deployments (BLUE_WAVES_ALLOW_LOCAL_FALLBACK=false) ban it
    #: for every quality tier.
    CLOUD_ONLY_QUALITIES = ("high", "premium")

    def _provider_candidates(self, preferred_provider: str, quality: str) -> list[Any]:
        if self._providers:
            # For high/premium: prefer Suno, then aimlapi, then ace_step, then local
            if quality in ("high", "premium"):
                preferred = preferred_provider if preferred_provider != "ace_step" else "suno_api"
            else:
                preferred = preferred_provider if preferred_provider != "suno_api" else None
            candidates = self._providers.configured_media_candidates("music", preferred, quality)
            from .providers import allows_local_pixels
            if quality in self.CLOUD_ONLY_QUALITIES or not allows_local_pixels(self._settings):
                cloud = [p for p in candidates if p.name != "local_audio_fallback"]
                if cloud or not allows_local_pixels(self._settings):
                    # Possibly empty under a strict ban: the engine then fails
                    # loudly instead of rendering synth noise.
                    return cloud
            return candidates
        return [self._select_provider(preferred_provider)]

    def _select_provider(self, provider_name: str) -> Any:
        if self._providers:
            try:
                return self._providers.get_music_provider(provider_name)
            except ProviderUnavailable:
                return self._providers.get_music_provider("local_audio_fallback")
        from .providers import AimlapiMusicProvider
        return AimlapiMusicProvider()

    def _generate_lyrics(self, topic: str, genre: str, mood: str) -> str:
        """Generate structured lyrics using LLM when available, or a template fallback.

        Song structure: Verse 1 -> Pre-Chorus -> Chorus -> Verse 2 -> Bridge -> Chorus -> Outro
        """
        # Try LLM generation first
        if self._providers and hasattr(self._providers, '_text'):
            try:
                from .providers import OpenAICompatibleProvider
                text_provider = self._providers._text.get("local")
                if text_provider and text_provider.configured:
                    system = "You are a professional songwriter. Write structured lyrics with verse/chorus/bridge sections."
                    user = (
                        f"Write {genre} song lyrics about '{topic}' with a {mood} mood. "
                        f"Include sections: [Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Bridge], [Chorus], [Outro]. "
                        f"Keep it under 300 words. Make it catchy and memorable."
                    )
                    completion = text_provider.complete(system, user)
                    if completion.text and len(completion.text) > 50:
                        return completion.text
            except Exception:
                pass

        # Template fallback — still produces structured, singable lyrics
        title = topic[:40].strip()
        return (
            f"[Verse 1]\n"
            f"In the light of dawn, we rise again\n"
            f"Chasing dreams through the {mood} rain\n"
            f"Every step we take, the world unfolds\n"
            f"A story yet to be told\n\n"
            f"[Pre-Chorus]\n"
            f"Can you feel it? The moment calling\n"
            f"Can you hear it? The silence falling\n\n"
            f"[Chorus]\n"
            f"We are the ones who never fade\n"
            f"{title}, we make our way\n"
            f"Through the {genre} beat, we come alive\n"
            f"This is our moment to thrive\n\n"
            f"[Verse 2]\n"
            f"Shadows break across the floor\n"
            f"Every heartbeat opens a door\n"
            f"We were never meant to stand still\n"
            f"Moving forward, we always will\n\n"
            f"[Bridge]\n"
            f"And when the night comes crashing down\n"
            f"We'll be the light in this town\n"
            f"No fear, no doubt, no turning back\n"
            f"We leave behind every track\n\n"
            f"[Chorus]\n"
            f"We are the ones who never fade\n"
            f"{title}, we make our way\n"
            f"Through the {genre} beat, we come alive\n"
            f"This is our moment to thrive\n\n"
            f"[Outro]\n"
            f"We rise, we rise, we rise again\n"
            f"This is where it all begins\n"
        )

    def compose_multiple(self, prompts: list[dict[str, Any]]) -> list[MusicGenerationResult]:
        results = []
        for prompt_data in prompts:
            result = self.generate(
                topic=prompt_data.get("topic", "unknown"),
                genre=prompt_data.get("genre", "cinematic"),
                mood=prompt_data.get("mood", "inspirational"),
                duration_seconds=prompt_data.get("duration_seconds", 180),
                lyrics=prompt_data.get("lyrics", ""),
                preferred_provider=prompt_data.get("provider", "suno_api"),
                quality=prompt_data.get("quality", "high"),
            )
            results.append(result)
        return results
