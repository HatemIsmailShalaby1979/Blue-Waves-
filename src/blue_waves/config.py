from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    tenant_id: str = "bluewaves"
    owner_actor: str = "hatem"
    data_dir: Path = Path("data")
    max_weekly_publishes: int = 5
    monthly_cloud_cents: int = 0
    local_llm_base_url: str = "http://127.0.0.1:1234/v1"
    local_llm_model: str = "qwen2.5-7b-instruct"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: str | None = None
    groq_model: str | None = None
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_api_key: str | None = None
    nvidia_nim_model: str | None = None
    codex_base_url: str | None = None
    codex_api_key: str | None = None
    ffmpeg_bin: str = "ffmpeg"
    piper_bin: str = "piper"
    edge_tts_bin: str = "edge-tts"
    ace_step_bin: str | None = None
    comfyui_base_url: str | None = None
    suno_api_key: str | None = None
    suno_base_url: str = "https://api.suno.ai/v1"
    kling_api_key: str | None = None
    kling_base_url: str = "https://api.klingai.com/v1"
    seedance_api_key: str | None = None
    seedance_base_url: str = "https://api.seedance.com/v1"
    kokoro_api_key: str | None = None
    kokoro_base_url: str = "https://api.kokoro.dev/v1"
    google_tts_credentials_path: str | None = None
    youtube_channel_id: str | None = None
    youtube_upload_enabled: bool = False
    youtube_oauth_client_id: str | None = None
    youtube_oauth_client_secret: str | None = None
    podcast_publish_enabled: bool = False
    music_publish_enabled: bool = False
    cockpit_host: str = "0.0.0.0"
    cockpit_port: int = 8420
    cockpit_secret_key: str = "change-me-in-production"
    cockpit_username: str = "hatem"
    cockpit_password_hash: str = ""
    scheduler_enabled: bool = True
    scheduler_max_concurrent: int = 3
    provider_fallback_enabled: bool = True
    quality_gate_threshold: float = 0.7
    max_weekly_music: int = 20
    max_weekly_podcasts: int = 5
    max_weekly_videos: int = 10
    max_podcast_duration_minutes: int = 60
    max_music_duration_seconds: int = 600
    auto_approve_under_cents: int = 0

    @classmethod
    def from_env(cls) -> "Settings":
        # Load .env file from project root (3 levels up from config.py: blue_waves -> src -> project_root)
        load_dotenv(Path(__file__).parent.parent.parent / ".env")
        
        def integer(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            return value

        def boolean(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            return raw.lower() in ("1", "true", "yes")

        return cls(
            tenant_id=os.getenv("BLUE_WAVES_TENANT_ID", "bluewaves"),
            owner_actor=os.getenv("BLUE_WAVES_OWNER_ACTOR", "hatem"),
            data_dir=Path(os.getenv("BLUE_WAVES_DATA_DIR", "data")),
            max_weekly_publishes=integer("BLUE_WAVES_MAX_WEEKLY_PUBLISHES", 5),
            monthly_cloud_cents=integer("BLUE_WAVES_MONTHLY_CLOUD_CENTS", 0),
            local_llm_base_url=os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
            local_llm_model=os.getenv("LM_STUDIO_MODEL", "qwen2.5-7b-instruct"),
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
            openrouter_model=os.getenv("OPENROUTER_MODEL") or None,
            groq_base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            groq_api_key=os.getenv("GROQ_API_KEY") or None,
            groq_model=os.getenv("GROQ_MODEL") or None,
            nvidia_nim_base_url=os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            nvidia_nim_api_key=os.getenv("NVIDIA_NIM_API_KEY") or None,
            nvidia_nim_model=os.getenv("NVIDIA_NIM_MODEL") or None,
            codex_base_url=os.getenv("BLUE_WAVES_CODEX_BASE_URL") or None,
            codex_api_key=os.getenv("BLUE_WAVES_CODEX_API_KEY") or None,
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
            piper_bin=os.getenv("PIPER_BIN", "piper"),
            edge_tts_bin=os.getenv("EDGE_TTS_BIN", "edge-tts"),
            ace_step_bin=os.getenv("ACE_STEP_BIN") or None,
            comfyui_base_url=os.getenv("COMFYUI_BASE_URL") or None,
            suno_api_key=os.getenv("SUNO_API_KEY") or None,
            suno_base_url=os.getenv("SUNO_BASE_URL", "https://api.suno.ai/v1"),
            kling_api_key=os.getenv("KLING_API_KEY") or None,
            kling_base_url=os.getenv("KLING_BASE_URL", "https://api.klingai.com/v1"),
            seedance_api_key=os.getenv("SEEDANCE_API_KEY") or None,
            seedance_base_url=os.getenv("SEEDANCE_BASE_URL", "https://api.seedance.com/v1"),
            kokoro_api_key=os.getenv("KOKORO_API_KEY") or None,
            kokoro_base_url=os.getenv("KOKORO_BASE_URL", "https://api.kokoro.dev/v1"),
            google_tts_credentials_path=os.getenv("GOOGLE_TTS_CREDENTIALS_PATH") or None,
            youtube_channel_id=os.getenv("YOUTUBE_CHANNEL_ID") or None,
            youtube_upload_enabled=boolean("YOUTUBE_UPLOAD_ENABLED", False),
            youtube_oauth_client_id=os.getenv("YOUTUBE_OAUTH_CLIENT_ID") or None,
            youtube_oauth_client_secret=os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET") or None,
            podcast_publish_enabled=boolean("PODCAST_PUBLISH_ENABLED", False),
            music_publish_enabled=boolean("MUSIC_PUBLISH_ENABLED", False),
            cockpit_host=os.getenv("COCKPIT_HOST", "0.0.0.0"),
            cockpit_port=integer("COCKPIT_PORT", 8420),
            cockpit_secret_key=os.getenv("COCKPIT_SECRET_KEY", "change-me-in-production"),
            cockpit_username=os.getenv("COCKPIT_USERNAME", "hatem"),
            cockpit_password_hash=os.getenv("COCKPIT_PASSWORD_HASH", ""),
            scheduler_enabled=boolean("SCHEDULER_ENABLED", True),
            scheduler_max_concurrent=integer("SCHEDULER_MAX_CONCURRENT", 3),
            provider_fallback_enabled=boolean("PROVIDER_FALLBACK_ENABLED", True),
            quality_gate_threshold=float(os.getenv("QUALITY_GATE_THRESHOLD", "0.7")),
            max_weekly_music=integer("BLUE_WAVES_MAX_WEEKLY_MUSIC", 20),
            max_weekly_podcasts=integer("BLUE_WAVES_MAX_WEEKLY_PODCASTS", 5),
            max_weekly_videos=integer("BLUE_WAVES_MAX_WEEKLY_VIDEOS", 10),
            max_podcast_duration_minutes=integer("BLUE_WAVES_MAX_PODCAST_DURATION_MINUTES", 60),
            max_music_duration_seconds=integer("BLUE_WAVES_MAX_MUSIC_DURATION_SECONDS", 600),
            auto_approve_under_cents=integer("BLUE_WAVES_AUTO_APPROVE_UNDER_CENTS", 0),
        )

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir
