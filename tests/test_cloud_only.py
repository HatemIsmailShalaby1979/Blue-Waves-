"""Phase B: strict production bans local pixel generation (loud failure, no noise)."""
from __future__ import annotations

from dataclasses import replace

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.providers import (
    LOCAL_PIXEL_PROVIDERS,
    allows_local_pixels,
    without_local_pixels,
)


def _strict_app(tmp_path) -> BlueWavesApplication:
    settings = replace(Settings(data_dir=tmp_path, youtube_upload_enabled=False),
                       allow_local_fallback=False)
    return BlueWavesApplication(settings)


def test_local_pixel_set():
    assert LOCAL_PIXEL_PROVIDERS == {"local_audio_fallback", "ken_burns", "local_tts_fallback"}
    assert allows_local_pixels(Settings()) is True
    strict = replace(Settings(), allow_local_fallback=False)
    assert allows_local_pixels(strict) is False


def test_without_local_pixels_filters():
    class Fake:
        def __init__(self, name: str):
            self.name = name

    cands = [Fake("aimlapi_music"), Fake("local_audio_fallback"), Fake("ace_step")]
    assert [p.name for p in without_local_pixels(cands, Settings())] == [
        "aimlapi_music", "local_audio_fallback", "ace_step"]
    strict = replace(Settings(), allow_local_fallback=False)
    assert [p.name for p in without_local_pixels(cands, strict)] == [
        "aimlapi_music", "ace_step"]


def test_strict_video_fails_loudly_without_cloud(tmp_path):
    """No cloud video configured + ban active → None, no render attempted."""
    app = _strict_app(tmp_path)
    assert app.generate_video(topic="t", prompt="p", duration=2, quality="draft") is None
    assert list(tmp_path.glob("videos/*")) == []


def test_strict_music_fails_loudly_without_funds(tmp_path):
    """aimlapi $0 + kai dead + ban → None with ledger reasons, never synth."""
    app = _strict_app(tmp_path)
    assert app.generate_music(topic="t", duration_seconds=10, quality="free") is None
    assert list(tmp_path.glob("music/*")) == []
