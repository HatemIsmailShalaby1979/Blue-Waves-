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
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from .models import CostEvent, now_iso
from .provider_rotation import ProviderCapability, ProviderRotationMatrix
from .toolchain import (
    AUDIO_SAMPLE_RATE,
    LOUDNORM_FILTER,
    Toolchain,
    audio_output_args,
    find_font,
    probe_duration,
)
from .enhancement import RESOLUTIONS


# Ken Burns pans and crossfades are continuous motion. At 24 fps the zoom
# visibly stutters; 30 fps is the point where it reads as smooth without
# quadrupling encode time. Kept in one place so the render and the
# crossfade maths can never drift apart.
VIDEO_FPS = 30


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
            "seedance": "ken_burns",
            "suno_api": "aimlapi_music",
            "aimlapi_music": "ace_step",
            "ace_step": "local_audio_fallback",
            "kokoro": "elevenlabs_tts",
            "elevenlabs_tts": "edge_tts",
            "google_tts": "elevenlabs_tts",
            "edge_tts": "local_tts_fallback",
        }
        return fallbacks.get(primary_provider, "ken_burns")

    def get_status(self) -> dict[str, dict[str, Any]]:
        return dict(self._health)


# The catalog is deliberately metadata, not a claim that every provider is enabled.
# Provider quotas and model names change frequently; the Cockpit exposes these entries
# and the owner supplies the current key/model. Only configured providers enter routing.
CLOUD_TEXT_CATALOG: tuple[dict[str, Any], ...] = (
    {"id": "openrouter", "type": "text", "free_quota": "model-dependent", "docs": "https://openrouter.ai/docs"},
    {"id": "groq", "type": "text", "free_quota": "developer-tier", "docs": "https://console.groq.com/docs"},
    {"id": "nvidia_nim", "type": "text", "free_quota": "credits-dependent", "docs": "https://docs.api.nvidia.com"},
    {"id": "cerebras", "type": "text", "free_quota": "developer-tier", "docs": "https://inference-docs.cerebras.ai"},
    {"id": "huggingface", "type": "text", "free_quota": "account-dependent", "docs": "https://huggingface.co/docs/api-inference"},
)


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
        _validate_url(self.base_url, ALLOWED_OPENAI_HOSTS)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        payload = json.dumps(body).encode("utf-8")
        request = _api_request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
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
            "openrouter", settings.openrouter_base_url, settings.openrouter_model or "openrouter/free", settings.openrouter_api_key
        ),
        "groq": OpenAICompatibleProvider(
            "groq", settings.groq_base_url, settings.groq_model or "llama-3.1-8b-instant", settings.groq_api_key
        ),
        "nvidia_nim": OpenAICompatibleProvider(
            "nvidia_nim", settings.nvidia_nim_base_url, settings.nvidia_nim_model or "meta/llama-3.1-8b-instruct", settings.nvidia_nim_api_key
        ),
        "cerebras": OpenAICompatibleProvider(
            "cerebras", settings.cerebras_base_url, settings.cerebras_model or "llama-3.3-70b", settings.cerebras_api_key
        ),
        "huggingface": OpenAICompatibleProvider(
            "huggingface", settings.huggingface_base_url, settings.huggingface_model or "meta-llama/Llama-3.2-3B-Instruct", settings.huggingface_api_key
        ),
    }


class ACEStepMusicProvider:
    """ACE-Step 1.5 music generation (local ROCm)."""

    def __init__(self) -> None:
        self.name = "ace_step"

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        raise ProviderUnavailable("ACE-Step requires ROCm GPU; use InMemoryMusicProvider for testing")


ALLOWED_OPENAI_HOSTS = {
    "api.openai.com",
    "api.openrouter.ai",
    "openrouter.ai",
    "api.groq.com",
    "integrate.api.nvidia.com",
    "api.cerebras.ai",
    "router.huggingface.co",
    "huggingface.co",
    "api-inference.huggingface.co",
    "localhost",
    "127.0.0.1",
}

ALLOWED_MEDIA_HOSTS = {
    "api.aimlapi.com",
    "api.kai.ai",
    "api.klingai.com",
    "api-singapore.klingai.com",
    "api.seedance.com",
    "api.kokoro.dev",
    "api.suno.ai",
    "api.elevenlabs.io",
    "api.pexels.com",
    "pixabay.com",
    "localhost",
    "127.0.0.1",
}

# Cloudflare-fronted APIs (Groq, Cerebras, aimlapi, …) reject Python-urllib's
# default User-Agent with error 1010. Identify as a real client everywhere.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 BlueWaves/0.3")


def _api_request(url: str, data: bytes | None = None,
                 headers: dict[str, str] | None = None,
                 method: str = "GET") -> urllib.request.Request:
    """Build an outbound API request with a Cloudflare-safe User-Agent."""
    merged = {"User-Agent": BROWSER_UA}
    if headers:
        merged.update(headers)
    return urllib.request.Request(url, data=data, headers=merged, method=method)


# Local *pixel* generators: PCM synth music, gradient KenBurns video, tone TTS.
# Banned in strict production (BLUE_WAVES_ALLOW_LOCAL_FALLBACK=false) because
# their output cannot compete with real creators. Local *assembly* (ffmpeg
# concat/mastering/loudnorm) creates no pixels and stays allowed, as do local
# neural models (ACE-Step) and free-tier cloud (Edge-TTS, Kokoro Docker).
LOCAL_PIXEL_PROVIDERS = frozenset({"local_audio_fallback", "ken_burns", "local_tts_fallback"})


def allows_local_pixels(settings: Any) -> bool:
    """True unless the deployment bans local pixel generation."""
    return bool(getattr(settings, "allow_local_fallback", True))


def without_local_pixels(candidates: list[Any], settings: Any) -> list[Any]:
    """Drop local pixel generators when the deployment bans them."""
    if allows_local_pixels(settings):
        return list(candidates)
    return [p for p in candidates if p.name not in LOCAL_PIXEL_PROVIDERS]


def _api_root(base_url: str) -> str:
    """Strip a trailing API version (``/v1``) so versioned paths join correctly.

    Without this, a base like ``https://api.aimlapi.com/v1`` combined with a
    ``/v2/...`` path produces ``/v1/v2/...`` → HTTP 404.
    """
    import re
    return re.sub(r"/v\d+/?$", "", (base_url or "").rstrip("/"))


def _validate_url(url: str, allowed_hosts: set[str] | None = None) -> None:
    """Validate URL to prevent SSRF."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ProviderUnavailable(f"Invalid URL scheme: {parsed.scheme}")
    
    hostname = parsed.hostname
    if not hostname:
        raise ProviderUnavailable("URL missing hostname")
    
    # Allow localhost for local development
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return
    
    # Check against allowed hosts
    hosts = allowed_hosts or ALLOWED_OPENAI_HOSTS
    if hostname not in hosts:
        raise ProviderUnavailable(f"Host not allowed: {hostname}")


class AimlapiMusicProvider:
    """aimlapi.com music generation (cloud) — minimax/music-2.0 or elevenlabs/eleven_music."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.aimlapi.com") -> None:
        self.name = "aimlapi_music"
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        if not self.api_key:
            raise ProviderUnavailable("aimlapi API key not configured")

        import urllib.request
        import json
        import time as _time

        _validate_url(self.base_url, ALLOWED_MEDIA_HOSTS)

        # Build a rich prompt combining style hints with the topic
        style_hints = f"{genre} {mood} music".strip()
        full_prompt = f"{style_hints}: {prompt}" if prompt else style_hints

        # Submit generation task — elevenlabs/eleven_music (no reference audio needed)
        body = {
            "model": "elevenlabs/eleven_music",
            "prompt": full_prompt[:2000],
            "music_length_ms": min(duration * 1000, 300000),
        }
        payload = json.dumps(body).encode("utf-8")
        root = _api_root(self.base_url)
        request = _api_request(
            f"{root}/v2/generate/audio",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise ProviderUnavailable(f"aimlapi submit failed ({exc.code}): {err_body[:300]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"aimlapi submit failed: {exc}") from exc

        gen_id = raw.get("generation_id") or raw.get("id")
        status = raw.get("status", "")
        if not gen_id:
            raise ProviderUnavailable(f"aimlapi returned no generation id: {raw}")

        # Poll until completed or error (max 5 minutes)
        deadline = _time.time() + 300
        while _time.time() < deadline:
            if status in ("completed", "done"):
                break
            if status in ("error", "failed"):
                err = raw.get("error", {})
                raise ProviderUnavailable(f"aimlapi generation error: {err.get('message', status)}")
            _time.sleep(10)
            poll_req = _api_request(
                f"{root}/v2/generate/audio?generation_id={gen_id}",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(poll_req, timeout=30) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                    status = raw.get("status", "")
            except Exception:
                continue

        if status not in ("completed", "done"):
            raise ProviderUnavailable(f"aimlapi generation timed out (status={status})")

        # Download the audio file
        audio_file = raw.get("audio_file") or {}
        audio_url = audio_file.get("url")
        if not audio_url:
            raise ProviderUnavailable(f"aimlapi returned no audio url: {raw}")

        try:
            dl_req = _api_request(audio_url, headers={"Authorization": f"Bearer {self.api_key}"})
            with urllib.request.urlopen(dl_req, timeout=120) as audio_resp:
                return audio_resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable(f"aimlapi audio download failed: {exc}") from exc


class KaiMusicProvider:
    """KAI.AI music generation (cloud) — disabled, API unreachable."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.kai.ai/v1") -> None:
        self.name = "kai_music"
        self.api_key = api_key
        self.base_url = base_url

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        raise ProviderUnavailable("KAI.AI API is unreachable — domain does not resolve")


def _is_local_url(url: str) -> bool:
    """True when a base URL points at a self-hosted endpoint (no API key needed)."""
    try:
        return (urllib.parse.urlparse(url).hostname or "") in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False


class KokoroTTSProvider:
    """Kokoro TTS (self-hosted Docker or hosted API).

    No account or API key is required when pointed at a local deployment, e.g.
    the ``kokoro-fastapi-cpu`` Docker image exposing an OpenAI-compatible
    endpoint::

        docker run -p 8880:8880 --name kokoro-tts-cpu ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.2

    with ``KOKORO_BASE_URL=http://localhost:8880/v1`` and a blank key
    (``"not-needed"`` also works). A hosted endpoint still needs its API key.
    Without either, raises so the provider chain falls through to edge_tts.
    """

    # ElevenLabs voice IDs → Kokoro voices (host=Adam→am_adam, guest=Bella→af_bella).
    ELEVENLABS_TO_KOKORO = {
        "21m00Tcm4TlvDq8ikWAM": "am_adam",
        "EXAVITQu4vr4xnSDxMaL": "af_bella",
        "ErXwobaYiN019PkySvjV": "am_michael",
        "VR6AayLTfiWG1GfLtjXk": "am_michael",
        "AZnzlk1XvdvUvBbpVxZ1": "af_nicole",
    }

    # Native Kokoro voices (af_* female, am_* male, bf_*/bm_* British).
    VOICES = (
        "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
        "am_adam", "am_michael", "bf_emma", "bf_isabella", "bm_george",
    )

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.kokoro.dev/v1") -> None:
        self.name = "kokoro"
        self.api_key = (api_key or "").strip() or None
        if self.api_key == "not-needed":
            self.api_key = None
        self.base_url = base_url.rstrip("/")

    def generate(self, text: str, voice_id: str = "af_heart", **kwargs: Any) -> bytes:
        local = _is_local_url(self.base_url)
        if not self.api_key and not local:
            raise ProviderUnavailable(
                "Kokoro TTS needs an API key or a local deployment "
                "(set KOKORO_BASE_URL to e.g. http://localhost:8880/v1)"
            )
        voice_id = self.ELEVENLABS_TO_KOKORO.get(voice_id, voice_id)
        _validate_url(self.base_url, ALLOWED_MEDIA_HOSTS)
        body = json.dumps({
            "model": "kokoro",
            "input": text[:5000],
            "voice": voice_id,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = _api_request(
            f"{self.base_url}/audio/speech",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable(f"Kokoro TTS request failed: {exc}") from exc


class EdgeTTSProvider:
    """Edge-TTS (free, cloud)."""

    # ElevenLabs voice IDs → Edge equivalents (host=Adam→Guy, guest=Bella→Aria).
    ELEVENLABS_TO_EDGE = {
        "21m00Tcm4TlvDq8ikWAM": "en-US-GuyNeural",
        "EXAVITQu4vr4xnSDxMaL": "en-US-AriaNeural",
        "ErXwobaYiN019PkySvjV": "en-US-GuyNeural",
        "VR6AayLTfiWG1GfLtjXk": "en-US-ChristopherNeural",
        "AZnzlk1XvdvUvBbpVxZ1": "en-US-JennyNeural",
    }

    def __init__(self) -> None:
        self.name = "edge_tts"

    def generate(self, text: str, voice_id: str = "en-US-AriaNeural", **kwargs: Any) -> bytes:
        import asyncio
        from edge_tts import Communicate

        # Map ElevenLabs voice IDs to Edge voices so the ElevenLabs-first
        # chain degrades gracefully to edge_tts without an invalid-voice error.
        if voice_id in self.ELEVENLABS_TO_EDGE:
            voice_id = self.ELEVENLABS_TO_EDGE[voice_id]
        elif "-" not in voice_id:
            voice_id = "en-US-AriaNeural"

        # Validate inputs
        if not voice_id.replace("-", "").replace("_", "").isalnum():
            raise ProviderUnavailable("Invalid voice_id")
        if len(text) > 10000:
            raise ProviderUnavailable("Text too long")
        
        fd, output_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        
        try:
            asyncio.run(Communicate(text, voice_id).save(output_path))
            return Path(output_path).read_bytes()
        except Exception as exc:
            raise ProviderUnavailable(f"Edge-TTS generation failed: {exc}") from exc
        finally:
            try:
                os.unlink(output_path)
            except FileNotFoundError:
                pass


class GoogleTTSProvider:
    """Google Cloud TTS (paid, high quality).

    Uses the google-cloud-texttospeech library when credentials are configured.
    Falls through to ProviderUnavailable otherwise so the chain can use ElevenLabs.
    """

    def __init__(self, credentials_path: str | None = None) -> None:
        self.name = "google_tts"
        self.credentials_path = credentials_path

    def generate(self, text: str, voice_id: str = "en-US-Wavenet-D", **kwargs: Any) -> bytes:
        if not self.credentials_path:
            raise ProviderUnavailable("Google TTS credentials not configured")
        try:
            from google.cloud import texttospeech
        except ImportError as exc:
            raise ProviderUnavailable(
                "google-cloud-texttospeech not installed; run pip install google-cloud-texttospeech"
            ) from exc
        import os
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text[:5000])
        voice = texttospeech.VoiceSelectionParams(
            language_code=voice_id.rsplit("-", 2)[0] + "-" + voice_id.split("-")[1] if "-" in voice_id else "en-US",
            name=voice_id,
            ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            sample_rate_hertz=24000,
        )
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        return response.audio_content


def _aimlapi_video_generate(api_key: str, base_url: str, model: str, prompt: str,
                            duration: int = 5, aspect_ratio: str = "16:9") -> bytes:
    """Shared aimlapi v2 video generation with async polling."""
    import urllib.request
    import json
    import time as _time

    root = _api_root(base_url)

    body = {
        "model": model,
        "prompt": prompt[:2000],
        "duration": duration,
        "aspect_ratio": aspect_ratio,
    }
    payload = json.dumps(body).encode("utf-8")
    request = _api_request(
        f"{root}/v2/video/generations",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise ProviderUnavailable(f"aimlapi video submit failed ({exc.code}): {err_body[:300]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ProviderUnavailable(f"aimlapi video submit failed: {exc}") from exc

    gen_id = raw.get("generation_id") or raw.get("id")
    status = raw.get("status", "")
    if not gen_id:
        raise ProviderUnavailable(f"aimlapi returned no generation id: {raw}")

    # Poll until completed (max 10 minutes for video)
    deadline = _time.time() + 600
    while _time.time() < deadline:
        if status in ("completed", "done"):
            break
        if status in ("error", "failed"):
            err = raw.get("error", {})
            raise ProviderUnavailable(f"aimlapi video error: {err.get('message', status)}")
        _time.sleep(15)
        poll_req = _api_request(
            f"{root}/v2/video/generations?generation_id={gen_id}",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(poll_req, timeout=30) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                status = raw.get("status", "")
        except Exception:
            continue

    if status not in ("completed", "done"):
        raise ProviderUnavailable(f"aimlapi video generation timed out (status={status})")

    video = raw.get("video") or {}
    video_url = video.get("url")
    if not video_url:
        raise ProviderUnavailable(f"aimlapi returned no video url: {raw}")

    try:
        dl_req = _api_request(video_url)
        with urllib.request.urlopen(dl_req, timeout=120) as video_resp:
            return video_resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderUnavailable(f"aimlapi video download failed: {exc}") from exc


def _kling_native_request(api_key: str, base_url: str, path: str,
                            payload: dict[str, Any] | None,
                            timeout: int = 60) -> dict[str, Any]:
    """POST/GET against the native Kling API with error bodies surfaced."""
    import urllib.error
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {api_key}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = _api_request(url, data=data, headers=headers,
                       method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise ProviderUnavailable(f"kling request failed ({exc.code}): {err_body[:300]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ProviderUnavailable(f"kling request failed: {exc}") from exc


def _kling_parse_task(submit_raw: Any) -> str:
    """Extract a task id from Kling's submit response (tolerant)."""
    if isinstance(submit_raw, dict):
        data = submit_raw.get("data")
        if isinstance(data, dict) and data.get("task_id"):
            return str(data["task_id"])
        for key in ("task_id", "id"):
            if submit_raw.get(key):
                return str(submit_raw[key])
    raise ProviderUnavailable(f"kling returned no task id: {submit_raw}")


def _kling_parse_status(poll_raw: Any) -> tuple[str, str | None]:
    """Return (state, video_url); state in queued/running/completed/failed."""
    data = poll_raw.get("data", poll_raw) if isinstance(poll_raw, dict) else {}
    if not isinstance(data, dict):
        return "running", None
    raw_status = str(data.get("task_status") or data.get("status") or "").lower()
    if raw_status in ("succeed", "succeeded", "completed", "done", "success"):
        state = "completed"
    elif raw_status in ("failed", "fail", "error", "cancelled", "canceled"):
        state = "failed"
    else:
        state = "running"
    url: str | None = None
    result = data.get("task_result") or {}
    if isinstance(result, dict):
        videos = result.get("videos") or []
        if videos and isinstance(videos[0], dict):
            url = videos[0].get("url")
        url = url or result.get("url")
    url = url or data.get("video_url") or data.get("url")
    fail_reason = data.get("fail_reason") or data.get("message") or ""
    if state == "failed" and fail_reason:
        raise ProviderUnavailable(f"kling generation failed: {fail_reason}"[:300])
    return state, url


class KlingVideoProvider:
    """Kling AI video generation via the NATIVE Kling API.

    ``https://api-singapore.klingai.com`` with a console API key
    (``Authorization: Bearer``). Supports text-to-video AND image-to-video,
    which powers the last-frame continuation loop for long-form video:
    each scene starts from the previous scene's final frame.
    """

    name = "kling"
    provides_narration = False
    supports_image_to_video = True
    TEXT_MODEL = "kling-v2.6-std"
    IMAGE_MODEL = "kling-v2.6-std"

    def __init__(self, api_key: str | None = None,
                 base_url: str = "https://api-singapore.klingai.com") -> None:
        self.name = "kling"
        self.api_key = (api_key or "").strip() or None
        self.base_url = (base_url or "https://api-singapore.klingai.com").rstrip("/")

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 **kwargs: Any) -> bytes:
        if not self.api_key:
            raise ProviderUnavailable("Kling API key not configured")
        _validate_url(self.base_url, ALLOWED_MEDIA_HOSTS)
        clip = 10 if duration > 7 else 5  # native durations: 5 or 10 seconds
        raw = _kling_native_request(
            self.api_key, self.base_url, "/v1/videos/text2video",
            {"model": self.TEXT_MODEL, "prompt": prompt[:2500],
             "duration": clip, "aspect_ratio": "16:9"},
        )
        return self._poll_and_download(raw)

    def generate_from_image(self, image_bytes: bytes, prompt: str,
                            duration: int = 5, **kwargs: Any) -> bytes:
        """Image-to-video: continue from a reference frame (last-frame loop)."""
        if not self.api_key:
            raise ProviderUnavailable("Kling API key not configured")
        _validate_url(self.base_url, ALLOWED_MEDIA_HOSTS)
        import base64
        clip = 10 if duration > 7 else 5
        raw = _kling_native_request(
            self.api_key, self.base_url, "/v1/videos/image2video",
            {"model": self.IMAGE_MODEL, "prompt": prompt[:2500],
             "image": base64.b64encode(image_bytes).decode("ascii"),
             "duration": clip, "aspect_ratio": "16:9"},
        )
        return self._poll_and_download(raw)

    def _poll_and_download(self, submit_raw: dict[str, Any]) -> bytes:
        import time as _time
        task_id = _kling_parse_task(submit_raw)
        deadline = _time.time() + 600
        while _time.time() < deadline:
            poll = _kling_native_request(
                self.api_key or "", self.base_url, f"/v1/videos/{task_id}",
                None, timeout=30,
            )
            try:
                state, url = _kling_parse_status(poll)
            except ProviderUnavailable:
                raise
            except Exception as exc:
                raise ProviderUnavailable(f"kling poll parse failed: {exc}") from exc
            if state == "completed":
                if not url:
                    raise ProviderUnavailable(f"kling completed with no video url: {poll}")
                dl = _api_request(url)
                try:
                    with urllib.request.urlopen(dl, timeout=180) as resp:
                        payload = resp.read()
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    raise ProviderUnavailable(f"kling download failed: {exc}") from exc
                if not payload:
                    raise ProviderUnavailable("kling download produced empty output")
                return payload
            _time.sleep(15)
        raise ProviderUnavailable("kling generation timed out")


class SeedanceVideoProvider:
    """Seedance video generation via aimlapi gateway."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.aimlapi.com") -> None:
        self.name = "seedance"
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 **kwargs: Any) -> bytes:
        if not self.api_key:
            raise ProviderUnavailable("Seedance API key not configured")
        return _aimlapi_video_generate(
            api_key=self.api_key,
            base_url=self.base_url,
            model="bytedance/seedance-2-0",
            prompt=prompt,
            duration=min(duration, 15),
            aspect_ratio="16:9",
        )


class StockVideoProvider:
    """Free stock footage (Pexels, Pixabay fallback) normalized to delivery spec.

    Real photographed footage under free commercial licenses — the zero-cost
    B-roll backbone. Needs a free Pexels or Pixabay API key (2-minute signup).
    Clips carry ambient audio only (``provides_narration = False``); the
    engine mixes the TTS narration bed over them.
    """

    name = "stock"
    provides_narration = False

    def __init__(self, pexels_key: str | None = None, pixabay_key: str | None = None) -> None:
        self.name = "stock"
        self.pexels_key = (pexels_key or "").strip() or None
        self.pixabay_key = (pixabay_key or "").strip() or None
        self.last_license = ""

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 **kwargs: Any) -> bytes:
        from .enhancement import RESOLUTIONS
        width, height = RESOLUTIONS.get(resolution, RESOLUTIONS["720p"])
        words = [w for w in prompt.lower().split() if len(w) > 3][:3]
        query = " ".join(words) if words else "nature"
        raw = self._fetch_clip(query)
        return self._normalize(raw, width, height, duration)

    def _fetch_clip(self, query: str) -> bytes:
        import urllib.parse
        errors: list[str] = []
        if self.pexels_key:
            try:
                return self._fetch_pexels(query)
            except Exception as exc:
                errors.append(f"pexels: {exc}")
        if self.pixabay_key:
            try:
                return self._fetch_pixabay(query)
            except Exception as exc:
                errors.append(f"pixabay: {exc}")
        raise ProviderUnavailable(
            "stock footage unavailable (need a free PEXELS_API_KEY or PIXABAY_API_KEY)"
            + (f": {'; '.join(errors)}" if errors else "")
        )

    def _fetch_pexels(self, query: str) -> bytes:
        import urllib.parse
        params = urllib.parse.urlencode({
            "query": query, "per_page": 5, "orientation": "landscape",
        })
        req = _api_request(
            f"https://api.pexels.com/videos/search?{params}",
            headers={"Authorization": self.pexels_key or ""},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        videos = data.get("videos") or []
        if not videos:
            raise ProviderUnavailable(f"pexels: no videos for {query!r}")
        files = (videos[0].get("video_files") or [])
        files = [f for f in files if f.get("link")]
        if not files:
            raise ProviderUnavailable("pexels: no downloadable files")
        files.sort(key=lambda f: abs((f.get("width") or 1280) - 1280))
        self.last_license = f"Pexels (free license) id={videos[0].get('id')}"
        return self._download(files[0]["link"])

    def _fetch_pixabay(self, query: str) -> bytes:
        import urllib.parse
        params = urllib.parse.urlencode({
            "key": self.pixabay_key or "", "q": query, "per_page": 5,
        })
        req = _api_request(f"https://pixabay.com/api/videos/?{params}")
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        hits = data.get("hits") or []
        if not hits:
            raise ProviderUnavailable(f"pixabay: no videos for {query!r}")
        videos = (hits[0].get("videos") or {})
        for quality in ("large", "medium", "small", "tiny"):
            url = (videos.get(quality) or {}).get("url")
            if url:
                self.last_license = f"Pixabay (free license) id={hits[0].get('id')}"
                return self._download(url)
        raise ProviderUnavailable("pixabay: no downloadable files")

    @staticmethod
    def _download(url: str) -> bytes:
        req = _api_request(url)
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if len(data) < 50_000:
            raise ProviderUnavailable("stock download too small to be a clip")
        return data

    @staticmethod
    def _normalize(raw: bytes, width: int, height: int, duration: int) -> bytes:
        """Scale/pad any clip to the exact delivery geometry + 30fps + AAC."""
        fd_in, in_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd_in)
        fd_out, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd_out)
        try:
            Path(in_path).write_bytes(raw)
            command = [
                "ffmpeg", "-y", "-loglevel", "error", "-i", in_path,
                "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height},fps=30,format=yuv420p"),
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-t", str(max(1, duration)),
                "-movflags", "+faststart", out_path,
            ]
            subprocess.run(command, check=True, timeout=max(90, duration * 4 + 30),
                           capture_output=True)
            payload = Path(out_path).read_bytes()
            if not payload:
                raise ProviderUnavailable("stock normalize produced empty output")
            return payload
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ProviderUnavailable(f"stock normalize failed: {exc}") from exc
        finally:
            for path in (in_path, out_path):
                try:
                    Path(path).unlink()
                except FileNotFoundError:
                    pass


class KenBurnsProvider:
    """Local video fallback: TTS narration over an animated background with music.

    `prompt` is treated as the short on-screen title. `narration` is the script
    that is actually spoken; when the caller omits it the title is spoken, which
    reproduces the old behaviour but should not be the normal path.
    """

    VOICE = "en-US-GuyNeural"
    provides_narration = True

    def __init__(self, toolchain: "Toolchain | None" = None, settings: Any = None) -> None:
        self.name = "ken_burns"
        if toolchain is None:
            toolchain = Toolchain.from_settings(settings) if settings is not None else Toolchain()
        self._toolchain = toolchain

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p",
                 narration: str | None = None, music_mode: str = "ambient", **kwargs: Any) -> bytes:
        width, height = RESOLUTIONS.get(resolution, RESOLUTIONS["1080p"])
        spoken = (narration or "").strip() or prompt
        tmp_files: list[Path] = []
        try:
            # 1. Narration. A failure here must surface, not become a silent video.
            tts_path = self._generate_tts(spoken, duration)
            tmp_files.append(tts_path)
            speech_seconds = probe_duration(self._toolchain, tts_path)

            # 2. Background music
            music_path = self._generate_bg_music(prompt, duration, music_mode)
            tmp_files.append(music_path)

            # 3. Visual track
            video_path = self._render_video(prompt, width, height, duration, narration)
            tmp_files.append(video_path)

            # 4. Mix: video + narration + background music at the delivery spec
            output_fd, output_path = tempfile.mkstemp(suffix=".mp4")
            os.close(output_fd)
            output = Path(output_path)

            # Resample both inputs before amix so the narration's 24 kHz mono
            # cannot drag the whole mix down with it.
            filter_parts = (
                f"[1:a]aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,volume=0.18[music];"
                f"[2:a]aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,volume=1.0,"
                f"highpass=f=80[narr];"
                f"[music][narr]amix=inputs=2:duration=longest:dropout_transition=2,"
                f"atrim=0:{duration},{LOUDNORM_FILTER},apad=whole_dur={duration}[out]"
            )
            command = [
                self._toolchain.ffmpeg, "-y", "-loglevel", "error",
                "-i", str(video_path),      # 0: video
                "-i", str(music_path),       # 1: music
                "-i", str(tts_path),         # 2: narration
                "-filter_complex", filter_parts,
                "-map", "0:v",
                "-map", "[out]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                *audio_output_args(),
                "-t", str(duration),
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(output),
            ]
            subprocess.run(command, check=True, timeout=max(60, duration * 2 + 30), capture_output=True)
            payload = output.read_bytes()
            if not payload:
                raise ProviderUnavailable("FFmpeg produced an empty video")
            return payload
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ProviderUnavailable(f"FFmpeg video render failed: {exc}") from exc
        finally:
            for p in tmp_files:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass

    def _generate_tts(self, text: str, target_duration: int) -> Path:
        """Generate TTS narration from text using edge-tts.

        Raises ProviderUnavailable on failure. The previous version swallowed
        every exception and substituted silence, which produced mute videos that
        still passed the quality gate.
        """
        import asyncio

        try:
            from edge_tts import Communicate
        except ImportError as exc:  # undeclared dependency guard
            raise ProviderUnavailable(
                "edge-tts is not installed; run `pip install edge-tts`"
            ) from exc

        sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
        narration_text = ". ".join(sentences) + "."
        if len(narration_text) > 3000:
            narration_text = narration_text[:3000]

        fd, tts_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        path = Path(tts_path)
        try:
            asyncio.run(Communicate(narration_text, self.VOICE).save(str(path)))
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise ProviderUnavailable(f"narration synthesis failed: {exc}") from exc
        if path.stat().st_size == 0:
            path.unlink(missing_ok=True)
            raise ProviderUnavailable("narration synthesis produced an empty file")
        # Pad only the tail. Trailing silence at the end of a rendered video is
        # normal; the media quality gate rejects assets whose *speech* does not
        # cover enough of the runtime.
        tts_dur = probe_duration(self._toolchain, path)
        if tts_dur <= 0:
            path.unlink(missing_ok=True)
            raise ProviderUnavailable("narration duration could not be measured")
        if tts_dur < target_duration - 1:
            padded_fd, padded_path = tempfile.mkstemp(suffix=".mp3")
            os.close(padded_fd)
            padded = Path(padded_path)
            subprocess.run([
                self._toolchain.ffmpeg, "-y", "-loglevel", "error",
                "-i", str(path),
                "-af", f"apad=whole_dur={target_duration}",
                "-t", str(target_duration),
                str(padded),
            ], check=True, capture_output=True, timeout=60)
            path.unlink()
            return padded
        return path

    def _generate_bg_music(self, prompt: str, duration: int, music_mode: str = "procedural") -> Path:
        """Generate background music for the video (delivery spec: 48 kHz stereo).

        music_mode: "procedural" (default, synth), "ambient" (slow pads only), "silence" (no music)
        """
        if music_mode == "silence":
            return self._generate_silence(duration)

        if music_mode == "ambient":
            return self._generate_ambient_music(prompt, duration)

        # Default: procedural synth music
        import wave as wave_mod
        sample_rate = AUDIO_SAMPLE_RATE
        total_frames = sample_rate * duration
        seed = sum(ord(c) for c in prompt[:100])
        rng = seed

        def next_rand() -> float:
            nonlocal rng
            rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
            return (rng / 0x7FFFFFFF) * 2 - 1

        # Musical parameters
        bpm = 120
        beat_sec = 60.0 / bpm
        bar_sec = beat_sec * 4

        # Chord progression (frequencies in Hz)
        progressions = [
            [261.63, 329.63, 392.00],  # C major
            [220.00, 277.18, 329.63],  # A minor
            [293.66, 369.99, 440.00],  # D minor
            [246.94, 311.13, 369.99],  # B dim -> use G major
        ]
        prog_idx = seed % len(progressions)

        frames = bytearray()
        for i in range(total_frames):
            t = i / sample_rate
            bar_pos = t % bar_sec
            beat_pos = t % beat_sec
            chord_idx = int((t / bar_sec) % len(progressions))
            chord = progressions[(prog_idx + chord_idx) % len(progressions)]

            sample = 0.0

            # Bass note (root, octave down)
            bass_freq = chord[0] / 2
            bass_env = max(0, 1 - (beat_pos / beat_sec) * 1.5)
            sample += 0.25 * bass_env * math.sin(2 * math.pi * bass_freq * t)

            # Pad chords (sustained)
            for j, freq in enumerate(chord):
                detune = 1.0 + (next_rand() * 0.002)
                pad_vol = 0.12 * (0.6 + 0.4 * math.sin(2 * math.pi * 0.25 * t))
                sample += pad_vol * math.sin(2 * math.pi * freq * detune * t)

            # Hi-hat rhythm (noise burst on beats)
            if beat_pos < 0.03:
                sample += 0.08 * next_rand()

            # Kick drum (low freq thump on beat 1 and 3)
            beat_in_bar = int(beat_pos / beat_sec)
            if beat_in_bar in (0, 2) and beat_pos < 0.08:
                kick_freq = 60 * (1 - beat_pos / 0.08)
                kick_env = 1 - beat_pos / 0.08
                sample += 0.3 * kick_env * math.sin(2 * math.pi * kick_freq * t)

            # Melody (simple arpeggio)
            arp_freq = chord[int((beat_pos / beat_sec) * 3) % 3] * 2
            arp_env = 0.06 * max(0, 1 - (beat_pos / beat_sec))
            sample += arp_env * math.sin(2 * math.pi * arp_freq * t)

            # Soft clip (mono synth voice, duplicated to stereo below)
            sample = max(-0.85, min(0.85, sample))
            frames += struct.pack("<hh", int(sample * 28000), int(sample * 28000))

        fd, music_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        path = Path(music_path)
        with wave_mod.open(str(path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(bytes(frames))
        return path

    def _generate_ambient_music(self, prompt: str, duration: int) -> Path:
        """Generate ambient background music (slow evolving pads, no drums)."""
        import wave as wave_mod
        sample_rate = AUDIO_SAMPLE_RATE
        total_frames = sample_rate * duration
        seed = sum(ord(c) for c in prompt[:100])
        rng = seed

        def next_rand() -> float:
            nonlocal rng
            rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
            return (rng / 0x7FFFFFFF) * 2 - 1

        # Slow chord progression
        progressions = [
            [261.63, 329.63, 392.00],  # C major
            [220.00, 277.18, 329.63],  # A minor
            [293.66, 369.99, 440.00],  # D minor
            [246.94, 311.13, 369.99],  # G major
        ]
        prog_idx = seed % len(progressions)

        frames = bytearray()
        for i in range(total_frames):
            t = i / sample_rate
            chord_idx = int((t / 30.0) % len(progressions))  # Change chord every 30s
            chord = progressions[(prog_idx + chord_idx) % len(progressions)]

            sample = 0.0

            # Slow evolving pads
            for j, freq in enumerate(chord):
                detune = 1.0 + (next_rand() * 0.001)
                # Slow volume envelope
                env = 0.08 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.05 * t + j))
                sample += env * math.sin(2 * math.pi * freq * detune * t)

            # Subtle texture
            if next_rand() < 0.001:
                sample += 0.02 * next_rand()

            sample = max(-0.5, min(0.5, sample))
            frames += struct.pack("<hh", int(sample * 28000), int(sample * 28000))

        fd, music_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        path = Path(music_path)
        with wave_mod.open(str(path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(bytes(frames))
        return path

    def _generate_topic_images(self, prompt: str, width: int, height: int, count: int) -> list[Path]:
        """Generate on-topic imagery via a free, keyless text-to-image service.

        This is the Layer-2 open/free path: the visuals actually depict the
        requested topic instead of being pulled from unrelated stock categories.
        Returns an empty list on any failure so the caller can fall back to stock
        photos or the gradient background.
        """
        import urllib.parse
        import urllib.request

        topic = (prompt or "abstract background").strip()[:200]
        images: list[Path] = []
        for i in range(count):
            img_prompt = f"{topic}, cinematic, detailed, high quality"
            query = urllib.parse.urlencode({
                "width": width,
                "height": height,
                "nologo": "true",
                "seed": str(i * 13 + 7),
            })
            url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(img_prompt)}?{query}"
            try:
                req = _api_request(url)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
            except Exception:
                continue
            if len(data) > 2000 and data[:2] == b"\xff\xd8":
                fd, img_path = tempfile.mkstemp(suffix=".jpg")
                os.close(fd)
                Path(img_path).write_bytes(data)
                images.append(Path(img_path))
            if len(images) >= count:
                break
        return images

    def _download_images(self, prompt: str, width: int, height: int, count: int) -> list[Path]:
        """Download multiple relevant stock images; returns list of temp paths."""
        import urllib.request
        keywords = [w for w in prompt.lower().split() if len(w) > 3][:3]
        base_queries = [
            "+".join(keywords) if keywords else "nature",
            "psychology+personality",
            "abstract+concept",
            "nature+landscape",
            "technology+future",
        ]
        images: list[Path] = []
        for q in base_queries:
            if len(images) >= count:
                break
            for url_tpl in (
                f"https://loremflickr.com/{width}/{height}/{q}",
                f"https://picsum.photos/{width}/{height}",
            ):
                if len(images) >= count:
                    break
                try:
                    req = _api_request(url_tpl)
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = resp.read()
                        if len(data) > 5000:
                            fd, img_path = tempfile.mkstemp(suffix=".jpg")
                            os.close(fd)
                            Path(img_path).write_bytes(data)
                            images.append(Path(img_path))
                except Exception:
                    continue
        return images

    def _render_video(self, prompt: str, width: int, height: int, duration: int, narration: str | None = None) -> Path:
        """Render visual track: on-topic imagery (Ken Burns + crossfades) + text overlay."""
        fd, video_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        path = Path(video_path)

        # Use narration for text overlay if provided, else prompt
        text_source = (narration or "").strip() or prompt
        lines = self._wrap_text(text_source, max_chars=50)
        # Real newlines, not the two-character string "\n"; drawtext's
        # `line_spacing` only kicks in on actual newlines.
        text_content = "\n".join(lines[:8])

        fd2, text_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd2)
        Path(text_path).write_text(text_content, encoding="utf-8")

        font = find_font(bold=True)

        def _ffmpeg_escape(value: str) -> str:
            return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

        escaped_text_path = _ffmpeg_escape(_ffmpeg_escape(text_path))

        # Build the visual track from on-topic imagery (Layer-2 free text-to-image),
        # falling back to generic stock photos, then a gradient if all sources fail.
        num_images = min(max(1, duration // 15), 6)
        # Cap the source request: at 1080p the naive 2x request would ask the
        # image service for 4K frames, which is slow enough to time out.
        req_w = min(width * 2, 2048)
        req_h = min(height * 2, 2048)
        img_paths = self._generate_topic_images(prompt, req_w, req_h, num_images)
        if not img_paths:
            img_paths = self._download_images(prompt, req_w, req_h, num_images)

        if img_paths:
            try:
                return self._render_from_images(img_paths, text_path, escaped_text_path, font, width, height, duration, path, tmp_files)
            except Exception:
                pass
            finally:
                for p in img_paths:
                    p.unlink(missing_ok=True)

        return self._render_gradient_fallback(text_content, escaped_text_path, font, width, height, duration, path, text_path)

    def _render_from_images(self, img_paths: list[Path], text_path: str, escaped_text_path: str,
                            font: str | None, width: int, height: int, duration: int, path: Path,
                            tmp_files: list[Path] | None = None) -> Path:
        """Render video from multiple images with Ken Burns + crossfades."""
        tmp_files = tmp_files if tmp_files is not None else []
        def _ffmpeg_escape(value: str) -> str:
            return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

        num_images = len(img_paths)
        if num_images == 1:
            return self._render_from_image(img_paths[0], text_path, escaped_text_path, font, width, height, duration, path, text_content, tmp_files)

        # Calculate duration per image
        img_duration = duration / num_images
        zoom_end = 1.15
        zoom_rate = (zoom_end - 1.0) / (img_duration * 24)

        # Build filter graph for multiple images with crossfades
        inputs = []
        filter_parts = []

        for i, img_path in enumerate(img_paths):
            inputs.extend(["-loop", "1", "-i", str(img_path)])
            zoom_expr = f"zoom+{zoom_rate:.8f}"
            pan_x = "(iw-iw/zoom)/2"
            pan_y = "(ih-ih/zoom)/2"
            filter_parts.append(
                f"[{i}:v]zoompan=z='{zoom_expr}':x='{pan_x}':y='{pan_y}'"
                f":d={int(img_duration * VIDEO_FPS)}:s={width}x{height}"
                f":fps={VIDEO_FPS}[v{i}]"
            )

        # Crossfade chain
        if num_images == 2:
            filter_parts.append(f"[v0][v1]xfade=transition=fade:duration=1.5:offset={img_duration - 1.5}[vout]")
        else:
            # Chain crossfades: v0->v1, then result->v2, etc.
            prev = "v0"
            for i in range(1, num_images):
                offset = i * img_duration - 1.5
                if i == num_images - 1:
                    out_label = "[vout]"
                else:
                    out_label = f"[v{i}]"
                filter_parts.append(f"[{prev}][v{i}]xfade=transition=fade:duration=1.5:offset={offset}{out_label}")
                prev = f"v{i}"

        # Text overlay: progressive captions synced to the narration, so the
        # whole script is visible over the runtime and nothing overflows.
        drawtext = self._caption_filter(text_content, duration, font, tmp_files)

        filter_parts.append(f"[vout]{drawtext}[vtext]")
        filter_parts.append(f"[vtext]fade=t=in:st=0:d=1.5,fade=t=out:st={max(0, duration - 1.5)}:d=1.5[vfinal]")

        filter_complex = ";".join(filter_parts)

        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[vfinal]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            str(path),
        ]
        subprocess.run(command, check=True, timeout=max(60, duration + 30), capture_output=True)
        return path

    def _render_from_image(self, img_path: Path, text_path: str, escaped_text_path: str,
                           font: str | None, width: int, height: int, duration: int, path: Path,
                           text_content: str = "", tmp_files: list[Path] | None = None) -> Path:
        tmp_files = tmp_files if tmp_files is not None else []
        def _ffmpeg_escape(value: str) -> str:
            return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

        zoom_end = 1.15
        zoom_expr = f"zoom+{(zoom_end - 1.0) / (duration * VIDEO_FPS):.8f}"
        pan_x = f"(iw-iw/zoom)/2"
        pan_y = f"(ih-ih/zoom)/2"

        zoompan = (
            f"zoompan=z='{zoom_expr}':x='{pan_x}':y='{pan_y}'"
            f":d={duration * VIDEO_FPS}:s={width}x{height}:fps={VIDEO_FPS}"
        )

        drawtext = self._caption_filter(
            text_content or Path(text_path).read_text(encoding="utf-8"),
            duration, font, tmp_files,
        )

        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", str(img_path),
            "-filter_complex",
            f"{zoompan},{drawtext},"
            f"fade=t=in:st=0:d=1.5,fade=t=out:st={max(0, duration - 1.5)}:d=1.5",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            str(path),
        ]
        subprocess.run(command, check=True, timeout=max(45, duration + 20), capture_output=True)
        return path

    def _render_gradient_fallback(self, text_content: str, escaped_text_path: str,
                                  font: str | None, width: int, height: int,
                                  duration: int, path: Path, text_path: str) -> Path:
        def _ffmpeg_escape(value: str) -> str:
            return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

        drawtext = (
            f"drawtext=textfile={escaped_text_path}:"
            f"fontcolor=white:fontsize=36:line_spacing=12:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"borderw=2:bordercolor=black@0.6"
        )
        if font is not None:
            escaped_font = _ffmpeg_escape(_ffmpeg_escape(font))
            drawtext = (
                f"drawtext=fontfile={escaped_font}:textfile={escaped_text_path}:"
                f"fontcolor=white:fontsize=36:line_spacing=12:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:"
                f"borderw=2:bordercolor=black@0.6"
            )

        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"color=c=0x0a1628:s={width}x{height}:d={duration}:r=24",
            "-f", "lavfi", "-i",
            f"color=c=0x1a3a5c:s={width}x{height}:d={duration}:r=24",
            "-filter_complex",
            f"[0:v][1:v]blend=all_expr='A*(1-T/{duration})+B*(T/{duration})':shortest=1,"
            f"{drawtext},"
            f"fade=t=in:st=0:d=2,fade=t=out:st={max(0,duration-2)}:d=2",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            str(path),
        ]
        try:
            subprocess.run(command, check=True, timeout=max(30, duration + 15), capture_output=True)
        finally:
            try:
                Path(text_path).unlink()
            except FileNotFoundError:
                pass
        return path

    def _generate_silence(self, duration: int) -> Path:
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"anullsrc=r={AUDIO_SAMPLE_RATE}:cl=stereo",
            "-t", str(duration),
            str(Path(path)),
        ], check=True, capture_output=True, timeout=30)
        return Path(path)

    @staticmethod
    def _probe_duration(path: Path) -> float:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    @staticmethod
    def _wrap_text(text: str, max_chars: int = 50) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > max_chars:
                if current:
                    lines.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        if current:
            lines.append(current)
        return lines

    def _caption_cues(self, text: str, duration: float, max_chars: int = 58) -> list[tuple[str, float, float]]:
        """Split narration into timed caption cues.

        Dumping the whole script into one static overlay means it either
        overflows the frame or gets silently clipped, and the viewer never
        sees most of it. Instead each cue is short enough to fit, and is
        shown only while that part is being spoken (time is shared out in
        proportion to word count).
        """
        words = text.split()
        if not words or duration <= 0:
            return []
        chunks: list[str] = []
        cur: list[str] = []
        for word in words:
            if cur and len(" ".join(cur + [word])) > max_chars:
                chunks.append(" ".join(cur))
                cur = [word]
            else:
                cur.append(word)
        if cur:
            chunks.append(" ".join(cur))

        total = len(words)
        cues: list[tuple[str, float, float]] = []
        t = 0.0
        for chunk in chunks:
            span = duration * (len(chunk.split()) / total)
            cues.append((chunk, t, t + span))
            t += span
        return cues

    def _caption_filter(self, narration: str, duration: float, font: str | None,
                        tmp_files: list[Path]) -> str:
        """Build the caption overlay filter chain for a Ken Burns render.

        Returns a filter string that dims the bottom band and then layers one
        time-gated `drawtext` per caption cue.
        """
        import tempfile

        parts = ["drawbox=x=0:y=ih*0.7:w=iw:h=ih*0.3:color=black@0.45:t=fill"]
        font_opt = ""
        if font is not None:
            font_opt = f"fontfile={_ffmpeg_escape(_ffmpeg_escape(font))}:"

        for chunk, start, end in self._caption_cues(narration, duration):
            body = "\n".join(self._wrap_text(chunk, max_chars=34)[:3])
            fd, cue_path = tempfile.mkstemp(suffix=".txt")
            os.close(fd)
            Path(cue_path).write_text(body, encoding="utf-8")
            tmp_files.append(Path(cue_path))
            parts.append(
                f"drawtext={font_opt}textfile={_ffmpeg_escape(_ffmpeg_escape(cue_path))}:"
                f"fontcolor=white:fontsize=32:line_spacing=10:"
                f"x=max(20,(w-text_w)/2):y=h*0.75:"
                f"borderw=2:bordercolor=black@0.7:"
                f"enable='between(t,{start:.3f},{end:.3f})'"
            )
        return ",".join(parts)


def _tone_wav(text: str, seconds: int = 2) -> bytes:
    """Deterministic WAV fallback — generates a musical pattern, not a single tone."""
    import wave as wave_mod
    sample_rate = AUDIO_SAMPLE_RATE
    total_frames = sample_rate * max(1, seconds)
    seed = sum(ord(char) for char in text) & 0xFFFFFFFF

    rng = seed
    def _rand() -> float:
        nonlocal rng
        rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
        return (rng / 0x7FFFFFFF) * 2 - 1

    # Scale frequencies (C major pentatonic)
    base_note = 261.63 * (2 ** ((seed % 12) / 12.0))
    scale = [base_note * (2 ** (n / 12.0)) for n in [0, 2, 4, 7, 9, 12, 14, 16]]
    bpm = 100 + (seed % 60)
    beat_sec = 60.0 / bpm

    frames = bytearray()
    for i in range(total_frames):
        t = i / sample_rate
        beat = t / beat_sec
        sample = 0.0

        # Pad chord (3-note)
        chord_root = scale[int(beat / 4) % len(scale)]
        for offset in [0, 4, 7]:
            freq = chord_root * (2 ** (offset / 12.0))
            vol = 0.15 * (0.7 + 0.3 * math.sin(2 * math.pi * 0.5 * t))
            sample += vol * math.sin(2 * math.pi * freq * t)

        # Melody note on each beat
        melody_freq = scale[int(beat) % len(scale)] * 2
        beat_pos = t % beat_sec
        env = max(0, 1 - beat_pos / (beat_sec * 0.8))
        sample += 0.2 * env * math.sin(2 * math.pi * melody_freq * t)

        # Kick
        if beat_pos < 0.05:
            kick_env = 1 - beat_pos / 0.05
            sample += 0.25 * kick_env * math.sin(2 * math.pi * 55 * (1 - beat_pos / 0.05) * t)

        # Hi-hat noise
        if beat_pos < 0.015:
            sample += 0.06 * _rand()

        sample = max(-0.9, min(0.9, sample))
        frames += struct.pack("<hh", int(sample * 28000), int(sample * 28000))

    stream = io.BytesIO()
    with wave_mod.open(stream, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return stream.getvalue()


class SunoMusicProvider:
    """Suno API music generation — produces 3+ minute full songs with lyrics.

    The clear leader for AI music quality. Supports custom lyrics, genre tags,
    and structured song format (verse/chorus/bridge).
    Cost: ~8 credits/song (~$0.08).
    """

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.suno.ai/v1") -> None:
        self.name = "suno_api"
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        if not self.api_key:
            # Suno offers no public API key (free quota lives in the web account
            # and cannot be consumed here), so skip gracefully to aimlapi.
            raise ProviderUnavailable(
                "Suno has no API key configured (Suno offers no public API; "
                "cloud music routes via aimlapi)"
            )
        _validate_url(self.base_url, ALLOWED_MEDIA_HOSTS)

        # Build tags from genre + mood for Suno's tag system
        tags = f"{genre} {mood}".strip()
        full_prompt = prompt[:500] if prompt else f"{genre} {mood} instrumental"

        body = json.dumps({
            "prompt": full_prompt,
            "tags": tags[:200],
            "lyrics": lyrics[:3000] if lyrics else "",
            "duration": min(duration, 300),  # Suno max ~5 min
            "instrumental": not bool(lyrics),
        }).encode("utf-8")

        req = _api_request(
            f"{self.base_url}/songs/generate",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"Suno submit failed: {exc}") from exc

        song_id = raw.get("song_id") or raw.get("id")
        if not song_id:
            raise ProviderUnavailable(f"Suno returned no song id: {raw}")

        # Poll until completed (max 5 minutes)
        import time as _time
        deadline = _time.time() + 300
        status = raw.get("status", "pending")
        while _time.time() < deadline:
            if status in ("completed", "done", "success"):
                break
            if status in ("error", "failed"):
                err = raw.get("error", {})
                raise ProviderUnavailable(f"Suno generation error: {err.get('message', status)}")
            _time.sleep(8)
            poll_req = _api_request(
                f"{self.base_url}/songs/{song_id}",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(poll_req, timeout=30) as poll_resp:
                    raw = json.loads(poll_resp.read().decode("utf-8"))
                    status = raw.get("status", "")
            except Exception:
                continue

        if status not in ("completed", "done", "success"):
            raise ProviderUnavailable(f"Suno generation timed out (status={status})")

        # Download the audio file
        audio_url = raw.get("audio_url") or raw.get("url")
        if not audio_url:
            raise ProviderUnavailable(f"Suno returned no audio url: {raw}")

        try:
            dl_req = _api_request(audio_url, headers={"Authorization": f"Bearer {self.api_key}"})
            with urllib.request.urlopen(dl_req, timeout=120) as audio_resp:
                return audio_resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable(f"Suno audio download failed: {exc}") from exc


class ElevenLabsTTSProvider:
    """ElevenLabs TTS — natural, human-like voices for podcasts and narration.

    Supports voice cloning and multiple premium voices. Indistinguishable from
    human narration in blind tests.
    Cost: ~$0.30 per 1000 characters.
    """

    # Curated voice IDs for podcast hosts and guests
    VOICES = {
        "adam": "21m00Tcm4TlvDq8ikWAM",        # Deep male
        "bella": "EXAVITQu4vr4xnSDxMaL",        # Warm female
        "antoni": "ErXwobaYiN019PkySvjV",       # Young male
        "rachel": "21m00Tcm4TlvDq8ikWAM",        # Calm female (alias)
        "arnold": "VR6AayLTfiWG1GfLtjXk",        # Strong male
        "domi": "AZnzlk1XvdvUvBbpVxZ1",          # Young female
    }

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.elevenlabs.io/v1") -> None:
        self.name = "elevenlabs_tts"
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(self, text: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM", **kwargs: Any) -> bytes:
        if not self.api_key:
            raise ProviderUnavailable("ElevenLabs API key not configured")
        _validate_url(self.base_url, ALLOWED_MEDIA_HOSTS)

        # Resolve named voices to IDs
        voice_id = self.VOICES.get(voice_id, voice_id)
        if not voice_id or not voice_id.replace("-", "").replace("_", "").isalnum():
            raise ProviderUnavailable(f"Invalid voice_id: {voice_id}")
        if len(text) > 5000:
            text = text[:5000]

        body = json.dumps({
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }).encode("utf-8")

        req = _api_request(
            f"{self.base_url}/text-to-speech/{voice_id}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "xi-api-key": self.api_key,
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable(f"ElevenLabs TTS request failed: {exc}") from exc


class OfflineMusicProvider:
    name = "local_audio_fallback"

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        from .music_synth import compose, mix_to_wav_bytes
        mix, meta = compose(prompt, genre, mood, min(duration, 600), lyrics=lyrics)
        return mix_to_wav_bytes(mix)


class OfflineTTSProvider:
    name = "local_tts_fallback"

    def generate(self, text: str, voice_id: str = "default", **kwargs: Any) -> bytes:
        return _tone_wav(f"{voice_id}:{text}", 2)


def configured_music_providers(settings: Any) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    if settings.suno_api_key:
        providers["suno_api"] = SunoMusicProvider(settings.suno_api_key, settings.suno_base_url)
    if settings.aimlapi_api_key:
        providers["aimlapi_music"] = AimlapiMusicProvider(settings.aimlapi_api_key, settings.aimlapi_base_url)
    if settings.kai_api_key:
        providers["kai_music"] = KaiMusicProvider(settings.kai_api_key, settings.kai_base_url)
    if settings.ace_step_bin:
        providers["ace_step"] = ACEStepMusicProvider()
    providers["local_audio_fallback"] = OfflineMusicProvider()
    return providers


def configured_tts_providers(settings: Any) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    if hasattr(settings, "elevenlabs_api_key") and settings.elevenlabs_api_key:
        providers["elevenlabs_tts"] = ElevenLabsTTSProvider(settings.elevenlabs_api_key, settings.elevenlabs_base_url)
    kokoro_base = getattr(settings, "kokoro_base_url", "https://api.kokoro.dev/v1")
    if settings.kokoro_api_key or _is_local_url(kokoro_base):
        # Local Docker needs no key; a hosted endpoint still needs one.
        providers["kokoro"] = KokoroTTSProvider(settings.kokoro_api_key, kokoro_base)
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
    if getattr(settings, "pexels_api_key", None) or getattr(settings, "pixabay_api_key", None):
        providers["stock"] = StockVideoProvider(
            getattr(settings, "pexels_api_key", None),
            getattr(settings, "pixabay_api_key", None),
        )
    providers["ken_burns"] = KenBurnsProvider()
    return providers


class ProviderRegistry:
    """Central registry for all provider types."""

    def __init__(self, settings: Any, approval_store: Any = None, health_monitor: ProviderHealthMonitor | None = None) -> None:
        self._settings = settings
        self._text = configured_providers(settings)
        self._music = configured_music_providers(settings)
        self._tts = configured_tts_providers(settings)
        self._video = configured_video_providers(settings)
        self._health = health_monitor or ProviderHealthMonitor()
        self._approvals = approval_store
        rotation_path = getattr(settings, "provider_rotation_path", None)
        if rotation_path is not None and not Path(rotation_path).is_absolute():
            rotation_path = Path(settings.data_dir) / rotation_path
        self._rotation = ProviderRotationMatrix(rotation_path)
        self._register_capabilities()

    @property
    def rotation(self) -> ProviderRotationMatrix:
        return self._rotation

    def _register_capabilities(self) -> None:
        capabilities = {
            "suno_api": ProviderCapability("suno_api", ("music",), quality_rank=98, estimated_cents=8),
            "aimlapi_music": ProviderCapability("aimlapi_music", ("music",), quality_rank=90, estimated_cents=5),
            "kai_music": ProviderCapability("kai_music", ("music",), quality_rank=70, estimated_cents=1),
            "ace_step": ProviderCapability("ace_step", ("music",), mode="local", free_tier=True, estimated_cents=0, quality_rank=85),
            "local_audio_fallback": ProviderCapability("local_audio_fallback", ("music",), mode="local", free_tier=True, estimated_cents=0, quality_rank=30),
            "elevenlabs_tts": ProviderCapability("elevenlabs_tts", ("tts",), quality_rank=95, estimated_cents=3),
            "kokoro": ProviderCapability(
                "kokoro", ("tts",), quality_rank=85,
                # Self-hosted Docker is free and unlimited; hosted API costs ~1¢/1k chars.
                mode="local" if _is_local_url(getattr(self._settings, "kokoro_base_url", "")) else "cloud",
                free_tier=_is_local_url(getattr(self._settings, "kokoro_base_url", "")),
                estimated_cents=0 if _is_local_url(getattr(self._settings, "kokoro_base_url", "")) else 1,
            ),
            "google_tts": ProviderCapability("google_tts", ("tts",), quality_rank=90, estimated_cents=2),
            "edge_tts": ProviderCapability("edge_tts", ("tts",), free_tier=True, quality_rank=70, estimated_cents=0),
            "local_tts_fallback": ProviderCapability("local_tts_fallback", ("tts",), mode="local", free_tier=True, estimated_cents=0, quality_rank=25),
            "kling": ProviderCapability("kling", ("video",), quality_rank=95, estimated_cents=50),
            "seedance": ProviderCapability("seedance", ("video",), quality_rank=85, estimated_cents=30),
            "stock": ProviderCapability("stock", ("video",), free_tier=True, estimated_cents=0, quality_rank=70),
            "ken_burns": ProviderCapability("ken_burns", ("video",), mode="local", free_tier=True, estimated_cents=0, quality_rank=40),
        }
        for capability in capabilities.values():
            self._rotation.register(capability)

    @property
    def health(self) -> ProviderHealthMonitor:
        return self._health

    def _guard(self, provider_name: str) -> None:
        """Fail closed if a cloud provider has not been approved for use."""
        if self._approvals is not None:
            self._approvals.require(provider_name)

    def get_text_provider(self, name: str) -> OpenAICompatibleProvider:
        if name not in self._text:
            raise ProviderUnavailable(f"text provider {name} not found")
        # Retrieval is also used by the Cockpit to inspect configured connectors.
        # Actual generation candidates are approval-filtered below.
        return self._text[name]

    def get_music_provider(self, name: str) -> Any:
        if name not in self._music:
            raise ProviderUnavailable(f"music provider {name} not found")
        self._guard(name)
        return self._music[name]

    def get_tts_provider(self, name: str) -> Any:
        if name not in self._tts:
            raise ProviderUnavailable(f"tts provider {name} not found")
        self._guard(name)
        return self._tts[name]

    def get_video_provider(self, name: str) -> Any:
        if name not in self._video:
            raise ProviderUnavailable(f"video provider {name} not found")
        self._guard(name)
        return self._video[name]

    def list_providers(self) -> dict[str, list[str]]:
        return {
            "text": list(self._text.keys()),
            "music": list(self._music.keys()),
            "tts": list(self._tts.keys()),
            "video": list(self._video.keys()),
        }

    def configured_text_candidates(self, preferred: str | None = None) -> list[OpenAICompatibleProvider]:
        """Return every configured text provider in an explicit quality/fallback order."""
        names = [preferred] if preferred else []
        names.extend(name for name in ("openrouter", "groq", "cerebras", "nvidia_nim", "huggingface") if name not in names)
        candidates: list[OpenAICompatibleProvider] = []
        for name in names:
            provider = self._text.get(name)
            if provider is None or not provider.configured:
                continue
            try:
                self._guard(name)
            except Exception:
                continue
            candidates.append(provider)
        return candidates

    def estimated_cost_for(self, content_type: str, quality: str = "high") -> int:
        """Return the cost of the first currently eligible candidate.

        This lets governance permit a local/free fallback even when the caller
        requested high quality, while still blocking a paid-only route before it
        starts.
        """
        candidates = self.configured_media_candidates(content_type, quality=quality)
        if not candidates:
            return 0
        capability = self._rotation.capability(candidates[0].name)
        return capability.estimated_cents if capability else 0

    def configured_media_candidates(self, content_type: str, preferred: str | None = None, quality: str = "high") -> list[Any]:
        """Return configured cloud providers first, local fallback last.

        Cloud providers produce high-quality output but may fail (API down,
        quota exhausted, network error). Local providers always succeed but
        produce lower quality. The fallback chain tries every cloud provider
        before falling back to local.
        """
        groups = {"music": self._music, "tts": self._tts, "video": self._video}
        group = groups[content_type]
        names = [preferred] if preferred else []
        if content_type == "music":
            # Cloud first: suno → aimlapi → kai → ace_step → local fallback
            names.extend(("suno_api", "aimlapi_music", "kai_music", "ace_step", "local_audio_fallback"))
        elif content_type == "tts":
            # Cloud first: elevenlabs → kokoro → google_tts → edge_tts → local fallback
            names.extend(("elevenlabs_tts", "kokoro", "google_tts", "edge_tts", "local_tts_fallback"))
        else:
            # Cloud first: kling → seedance → stock (free footage) → ken_burns (local)
            names.extend(("kling", "seedance", "stock", "ken_burns"))
        unique_names = list(dict.fromkeys(name for name in names if name))
        ordered_names = self._rotation.ordered(unique_names, preferred=preferred, quality=quality)
        eligible: list[Any] = []
        for name in ordered_names:
            provider = group.get(name)
            if provider is None or not self._health.is_healthy(name):
                continue
            capability = self._rotation.capability(name)
            if capability and capability.mode == "cloud" and self._approvals is not None:
                try:
                    self._approvals.require(name)
                except Exception:
                    continue
            if capability and capability.mode == "cloud" and capability.estimated_cents > 0:
                if not self._rotation.eligible(name, monthly_budget_cents=getattr(self._settings, "monthly_cloud_cents", 0)):
                    continue
            eligible.append(provider)
        # Always retain the local safety net, even when cloud quota is exhausted.
        for name in unique_names:
            provider = group.get(name)
            capability = self._rotation.capability(name)
            if provider is not None and capability is not None and capability.mode == "local" and provider not in eligible:
                eligible.append(provider)
        return eligible

    def catalog(self) -> list[dict[str, Any]]:
        entries = [{"id": "lm_studio", "type": "text", "mode": "local", "credential": "none", "free_quota": "local", "configured": self._text["local"].configured}]
        entries.extend([
            dict(item, mode="cloud", credential="api_key", configured=self._text[item["id"]].configured)
            for item in CLOUD_TEXT_CATALOG
        ])
        entries.extend([
            {"id": "suno_api", "type": "music", "mode": "cloud", "credential": "api_key", "free_quota": "account-dependent", "configured": "suno_api" in self._music},
            {"id": "aimlapi_music", "type": "music", "mode": "cloud", "credential": "api_key", "free_quota": "account-dependent", "configured": "aimlapi_music" in self._music},
            {"id": "elevenlabs_tts", "type": "tts", "mode": "cloud", "credential": "api_key", "free_quota": "account-dependent", "configured": "elevenlabs_tts" in self._tts},
            {"id": "kokoro", "type": "tts", "mode": "cloud", "credential": "api_key", "free_quota": "self-host/free-tier dependent", "configured": "kokoro" in self._tts},
            {"id": "edge_tts", "type": "tts", "mode": "cloud", "credential": "none", "free_quota": "free", "configured": True},
            {"id": "kling", "type": "video", "mode": "cloud", "credential": "api_key", "free_quota": "account-dependent", "configured": "kling" in self._video},
            {"id": "seedance", "type": "video", "mode": "cloud", "credential": "api_key", "free_quota": "account-dependent", "configured": "seedance" in self._video},
            {"id": "stock", "type": "video", "mode": "cloud", "credential": "api_key", "free_quota": "free (Pexels/Pixabay key)", "configured": "stock" in self._video},
            {"id": "ken_burns", "type": "video", "mode": "local", "credential": "none", "free_quota": "free", "configured": True},
            {"id": "local_audio_fallback", "type": "music", "mode": "local", "credential": "none", "free_quota": "free", "configured": True},
            {"id": "local_tts_fallback", "type": "tts", "mode": "local", "credential": "none", "free_quota": "free", "configured": True},
        ])
        return entries
