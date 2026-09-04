"""Phase 10.2: Best-quality music E2E (lightweight, offline)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings


def _probe_audio(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels,codec_name",
         "-show_entries", "format=duration",
         "-of", "json", path],
        check=True, timeout=30, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def test_music_quality_short_free(tmp_path):
    """Free-tier music renders 48kHz stereo and passes the gate."""
    settings = Settings(data_dir=tmp_path, youtube_upload_enabled=False)
    app = BlueWavesApplication(settings)
    asset = app.generate_music(
        topic="lofi study beats",
        genre="lofi",
        mood="calm",
        duration_seconds=10,
        quality="free",
    )
    assert asset is not None, "music generation failed"
    assert asset.audio_path and Path(asset.audio_path).is_file()
    assert Path(asset.audio_path).stat().st_size > 10_000

    probe = _probe_audio(asset.audio_path)
    stream = (probe.get("streams") or [{}])[0]
    assert int(stream.get("sample_rate", 0)) == 48000
    assert int(stream.get("channels", 0)) == 2
    duration = float(probe.get("format", {}).get("duration", 0))
    assert abs(duration - 10) <= 3.0, f"duration {duration} far from 10s"

    check = app.quality_gates.check_media_asset(asset, asset.audio_path, "music")
    assert check.score >= 0.7, f"gate score low: {check.score} {check.issues}"
    assert check.passed, f"gate failed: {check.issues}"


def test_music_with_generated_lyrics(tmp_path):
    """LLM/template lyrics produce a structured song."""
    settings = Settings(data_dir=tmp_path, youtube_upload_enabled=False)
    app = BlueWavesApplication(settings)
    lyrics = app.music_engine._generate_lyrics("ocean waves", "cinematic", "inspirational")
    assert "[Verse 1]" in lyrics
    assert "[Chorus]" in lyrics
    # Full structure: verse, chorus, bridge, outro.
    for marker in ("[Verse 2]", "[Bridge]", "[Outro]"):
        assert marker in lyrics, f"missing section {marker}"

    asset = app.generate_music(
        topic="ocean waves",
        genre="cinematic",
        mood="inspirational",
        duration_seconds=10,
        quality="free",
    )
    assert asset is not None
    assert asset.lyrics, "engine should attach lyrics even when not provided"
    assert "[Chorus]" in asset.lyrics
