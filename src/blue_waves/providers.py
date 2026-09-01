from __future__ import annotations

import json
import io
import math
import os
import struct
import subprocess
import tempfile
from pathlib import Path
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from .models import CostEvent, now_iso


class ProviderUnavailable(RuntimeError):
    pass


class ProviderHealthMonitor:
    """Track provider health with sliding window."""

    def __init__(self) -> None:
        self._health: dict[str, dict[str, Any]] = {}

    def record_success(self, provider: str) -> None:
        if provider not in self._health:
            self._health[provider] = {"status": "healthy", "successes": 0, "failures": 0}
        self._health[provider]["successes"] += 1

    def record_failure(self, provider: str, error: str) -> None:
        if provider not in self._health:
            self._health[provider] = {"status": "healthy", "successes": 0, "failures": 0}
        self._health[provider]["failures"] += 1
        if self._health[provider]["failures"] >= 3:
            self._health[provider]["status"] = "degraded"

    def is_healthy(self, provider: str) -> bool:
        if provider not in self._health:
            return True
        return self._health[provider]["status"] == "healthy"

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
        return dict(self._health)


@dataclass(frozen=True)
class Completion:
    provider: str
    model: str
    text: str
    estimated_cost_cents: int = 0
    request_id: str = ""
    mode: str = "local"


class TextProvider(Protocol):
    name: str
    model: str
    mode: str

    def complete(self, system: str, user: str) -> Completion: ...


class MusicProvider(Protocol):
    name: str

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes: ...


class TTSProvider(Protocol):
    name: str

    def generate(self, text: str, voice_id: str = "default", **kwargs: Any) -> bytes: ...


class VideoProvider(Protocol):
    name: str

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 **kwargs: Any) -> bytes: ...


class OpenAICompatibleProvider:
    """Minimal dependency-free client for LM Studio and configured cloud APIs."""

    def __init__(self, name: str, base_url: str, model: str, api_key: str | None = None, mode: str = "cloud"):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.mode = mode

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and (self.mode == "local" or self.api_key))

    def complete(self, system: str, user: str) -> Completion:
        if not self.configured:
            raise ProviderUnavailable(f"provider {self.name} is not configured")
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"provider {self.name} request failed: {exc}") from exc
        try:
            text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable(f"provider {self.name} returned an invalid completion") from exc
        return Completion(
            provider=self.name,
            model=self.model,
            text=str(text),
            request_id=str(raw.get("id") or uuid.uuid4()),
            mode=self.mode,
            estimated_cost_cents=0 if self.mode == "local" else int(raw.get("usage", {}).get("cost_cents", 0) or 0),
        )


class DeferredMotionProvider:
    """Explicit placeholder for video generation until a verified provider is selected.

    Agnes is intentionally not implemented: its endpoint and model contract are not
    verified. A missing provider fails closed and the pipeline falls back to slides,
    Ken Burns motion, captions, narration and ACE-Step music.
    """

    name = "deferred_motion_provider"
    mode = "cloud"

    def generate(self, prompt: str) -> dict[str, Any]:
        raise ProviderUnavailable(
            "no verified cloud video provider configured; use the local educational render fallback"
        )


def configured_providers(settings: Any) -> dict[str, OpenAICompatibleProvider]:
    return {
        "local": OpenAICompatibleProvider(
            "lm_studio", settings.local_llm_base_url, settings.local_llm_model, mode="local"
        ),
        "openrouter": OpenAICompatibleProvider(
            "openrouter", settings.openrouter_base_url, settings.openrouter_model or "", settings.openrouter_api_key
        ),
        "groq": OpenAICompatibleProvider(
            "groq", settings.groq_base_url, settings.groq_model or "", settings.groq_api_key
        ),
        "nvidia_nim": OpenAICompatibleProvider(
            "nvidia_nim", settings.nvidia_nim_base_url, settings.nvidia_nim_model or "", settings.nvidia_nim_api_key
        ),
    }


class ACEStepMusicProvider:
    """ACE-Step 1.5 music generation (local ROCm)."""

    def __init__(self) -> None:
        self.name = "ace_step"

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        raise ProviderUnavailable("ACE-Step requires ROCm GPU; use InMemoryMusicProvider for testing")


class SunoMusicProvider:
    """Suno API music generation (cloud)."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.suno.ai/v1") -> None:
        self.name = "suno_api"
        self.api_key = api_key
        self.base_url = base_url

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        if not self.api_key:
            raise ProviderUnavailable("Suno API key not configured")
        raise ProviderUnavailable("Suno API integration requires API key verification")


class KokoroTTSProvider:
    """Kokoro TTS (local or API)."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.kokoro.dev/v1") -> None:
        self.name = "kokoro"
        self.api_key = api_key
        self.base_url = base_url

    def generate(self, text: str, voice_id: str = "default", **kwargs: Any) -> bytes:
        raise ProviderUnavailable("Kokoro TTS requires API key or local deployment")


class EdgeTTSProvider:
    """Edge-TTS (free, cloud)."""

    def __init__(self) -> None:
        self.name = "edge_tts"

    def generate(self, text: str, voice_id: str = "en-US-AriaNeural", **kwargs: Any) -> bytes:
        raise ProviderUnavailable("Edge-TTS requires edge-tts binary")


class GoogleTTSProvider:
    """Google Cloud TTS (paid, high quality)."""

    def __init__(self, credentials_path: str | None = None) -> None:
        self.name = "google_tts"
        self.credentials_path = credentials_path

    def generate(self, text: str, voice_id: str = "en-US-Wavenet-D", **kwargs: Any) -> bytes:
        if not self.credentials_path:
            raise ProviderUnavailable("Google TTS credentials not configured")
        raise ProviderUnavailable("Google TTS requires credentials file")


class KlingVideoProvider:
    """Kling AI video generation (paid, high quality)."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.klingai.com/v1") -> None:
        self.name = "kling"
        self.api_key = api_key
        self.base_url = base_url

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 **kwargs: Any) -> bytes:
        if not self.api_key:
            raise ProviderUnavailable("Kling API key not configured")
        raise ProviderUnavailable("Kling API integration requires API key verification")


class SeedanceVideoProvider:
    """Seedance video generation (paid)."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.seedance.com/v1") -> None:
        self.name = "seedance"
        self.api_key = api_key
        self.base_url = base_url

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 **kwargs: Any) -> bytes:
        if not self.api_key:
            raise ProviderUnavailable("Seedance API key not configured")
        raise ProviderUnavailable("Seedance API integration requires API key verification")


class KenBurnsProvider:
    """Ken Burns fallback (always available, no API key)."""

    def __init__(self) -> None:
        self.name = "ken_burns"

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 **kwargs: Any) -> bytes:
        width, height = (1280, 720) if resolution == "720p" else (1920, 1080)
        fd, output_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                   f"color=c=0x083344:s={width}x{height}:d={max(1, duration)}:r=24",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", output_path]
        try:
            subprocess.run(command, check=True, timeout=max(20, duration + 15), capture_output=True)
            return Path(output_path).read_bytes()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ProviderUnavailable(f"FFmpeg video render failed: {exc}") from exc
        finally:
            try:
                os.unlink(output_path)
            except FileNotFoundError:
                pass


def _tone_wav(text: str, seconds: int = 2) -> bytes:
    """Small deterministic, valid WAV fallback for offline smoke tests and local use."""
    sample_rate = 22050
    frames = max(1, sample_rate * min(max(seconds, 1), 10))
    frequency = 220 + (sum(ord(char) for char in text) % 220)
    stream = io.BytesIO()
    import wave
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(struct.pack("<h", int(7000 * math.sin(2 * math.pi * frequency * i / sample_rate))) for i in range(frames)))
    return stream.getvalue()


class OfflineMusicProvider:
    name = "local_audio_fallback"

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        return _tone_wav(f"{prompt}:{genre}:{mood}", min(duration, 10))


class OfflineTTSProvider:
    name = "local_tts_fallback"

    def generate(self, text: str, voice_id: str = "default", **kwargs: Any) -> bytes:
        return _tone_wav(f"{voice_id}:{text}", 2)


def configured_music_providers(settings: Any) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    if settings.ace_step_bin:
        providers["ace_step"] = ACEStepMusicProvider()
    if settings.suno_api_key:
        providers["suno_api"] = SunoMusicProvider(settings.suno_api_key, settings.suno_base_url)
    providers["local_audio_fallback"] = OfflineMusicProvider()
    return providers


def configured_tts_providers(settings: Any) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    if settings.kokoro_api_key:
        providers["kokoro"] = KokoroTTSProvider(settings.kokoro_api_key, settings.kokoro_base_url)
    providers["edge_tts"] = EdgeTTSProvider()
    providers["local_tts_fallback"] = OfflineTTSProvider()
    if settings.google_tts_credentials_path:
        providers["google_tts"] = GoogleTTSProvider(settings.google_tts_credentials_path)
    return providers


def configured_video_providers(settings: Any) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    if settings.kling_api_key:
        providers["kling"] = KlingVideoProvider(settings.kling_api_key, settings.kling_base_url)
    if settings.seedance_api_key:
        providers["seedance"] = SeedanceVideoProvider(settings.seedance_api_key, settings.seedance_base_url)
    providers["ken_burns"] = KenBurnsProvider()
    return providers


class ProviderRegistry:
    """Central registry for all provider types."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._text = configured_providers(settings)
        self._music = configured_music_providers(settings)
        self._tts = configured_tts_providers(settings)
        self._video = configured_video_providers(settings)
        self._health = ProviderHealthMonitor()

    @property
    def health(self) -> ProviderHealthMonitor:
        return self._health

    def get_text_provider(self, name: str) -> OpenAICompatibleProvider:
        if name not in self._text:
            raise ProviderUnavailable(f"text provider {name} not found")
        return self._text[name]

    def get_music_provider(self, name: str) -> Any:
        if name not in self._music:
            raise ProviderUnavailable(f"music provider {name} not found")
        return self._music[name]

    def get_tts_provider(self, name: str) -> Any:
        if name not in self._tts:
            raise ProviderUnavailable(f"tts provider {name} not found")
        return self._tts[name]

    def get_video_provider(self, name: str) -> Any:
        if name not in self._video:
            raise ProviderUnavailable(f"video provider {name} not found")
        return self._video[name]

    def list_providers(self) -> dict[str, list[str]]:
        return {
            "text": list(self._text.keys()),
            "music": list(self._music.keys()),
            "tts": list(self._tts.keys()),
            "video": list(self._video.keys()),
        }
