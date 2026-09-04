"""Phase 10.3: High-quality podcast E2E (lightweight, offline)."""
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


def test_podcast_high_quality_modern_voices(tmp_path):
    """Podcast renders 48kHz stereo, has two voices, and passes the gate."""
    settings = Settings(data_dir=tmp_path, youtube_upload_enabled=False)
    app = BlueWavesApplication(settings)
    asset = app.generate_podcast(
        topic="the science of sleep",
        script="Host: Welcome to the show. Guest: Thanks, sleep is fascinating. " * 4,
        quality="free",
        duration_seconds=12,
    )
    assert asset is not None, "podcast generation failed"
    assert asset.audio_path and Path(asset.audio_path).is_file()
    assert Path(asset.audio_path).stat().st_size > 5_000

    probe = _probe_audio(asset.audio_path)
    stream = (probe.get("streams") or [{}])[0]
    assert int(stream.get("sample_rate", 0)) == 48000
    assert int(stream.get("channels", 0)) == 2
    duration = float(probe.get("format", {}).get("duration", 0))
    assert duration > 3, f"podcast too short: {duration}s"

    # Two distinct voices are mandatory for dialogue podcasts.
    assert asset.host_voice, "missing host voice"
    assert asset.guest_voice, "missing guest voice"
    assert asset.host_voice != asset.guest_voice, "host and guest voices must differ"

    check = app.quality_gates.check_media_asset(asset, asset.audio_path, "podcast")
    assert check.score >= 0.5, f"gate score low: {check.score} {check.issues}"


def test_podcast_dialogue_has_two_speakers(tmp_path):
    """Dialogue builder produces host/guest turns that fill the duration."""
    from blue_waves.dialogue import build_dialogue

    turns = build_dialogue("the science of sleep", "en", 30,
                           "Host: Welcome. Guest: Thanks for having me.")
    assert len(turns) >= 2, "dialogue should have multiple turns"
    speakers = {speaker for speaker, _ in turns}
    assert "host" in speakers and "guest" in speakers, f"need two speakers, got {speakers}"
    total_text = " ".join(text for _, text in turns)
    assert len(total_text) > 50, "dialogue too short to fill duration"
