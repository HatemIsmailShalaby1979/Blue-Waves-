"""Phase 10.1: Best-quality video E2E (lightweight, offline).

Generates short clips with quality="high" (1080p path) and verifies
YouTube-spec delivery: 1920x1080, h264, audio present, duration accurate,
and the quality gate passes.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.video_use_editor import VideoUseEditor


def _probe_streams(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,avg_frame_rate,sample_rate,channels,pix_fmt",
         "-show_entries", "format=duration",
         "-of", "json", path],
        check=True, timeout=30, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def _fps(rate: str) -> float:
    num, _, den = rate.partition("/")
    try:
        return float(num) / float(den or "1")
    except (ValueError, ZeroDivisionError):
        return 0.0


def test_video_high_quality_1080p_short(tmp_path):
    """High-quality path renders 1080p h264 with audio and passes the gate."""
    settings = Settings(data_dir=tmp_path, youtube_upload_enabled=False)
    app = BlueWavesApplication(settings)
    asset = app.generate_video(
        topic="how batteries work",
        prompt="educational title card about batteries",
        duration=3,
        quality="high",
    )
    assert asset is not None, "video generation failed"
    video_path = asset.media_manifest.get("video_path")
    assert video_path and Path(video_path).is_file()
    assert Path(video_path).stat().st_size > 10_000

    probe = _probe_streams(video_path)
    streams = probe.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    assert v is not None, "no video stream"
    assert a is not None, "video missing audio track"
    assert int(v.get("width", 0)) == 1920
    assert int(v.get("height", 0)) == 1080
    assert v.get("codec_name") == "h264"
    assert _fps(str(v.get("avg_frame_rate", "0/1"))) >= 23
    assert int(a.get("sample_rate", 0)) == 48000
    assert int(a.get("channels", 0)) == 2

    duration = float(probe.get("format", {}).get("duration", 0))
    assert abs(duration - 3) <= 2.0, f"duration {duration} far from 3s target"

    check = app.quality_gates.check_media_asset(asset, video_path, "video")
    assert check.score >= 0.7, f"gate score too low: {check.score} issues={check.issues}"
    assert check.passed, f"gate failed: {check.issues}"


def test_video_use_post_production(tmp_path):
    """VideoUseEditor adds overlays/grading and meets YouTube spec."""
    settings = Settings(data_dir=tmp_path, youtube_upload_enabled=False)
    app = BlueWavesApplication(settings)
    # Raw clip without post-production (draft is fastest).
    raw = app.video_engine.generate(
        topic="raw clip",
        prompt="simple title card",
        duration=3,
        quality="draft",
    )
    assert raw.success and raw.asset is not None
    raw_path = Path(str(raw.asset.media_manifest["video_path"]))
    assert raw_path.is_file()

    editor = VideoUseEditor(settings)
    result = editor.edit(
        raw_video_path=raw_path,
        transcript_text="This is a test narration. It has two sentences for captions.",
        narration_audio_path=None,
        topic="Test Title",
        duration=3,
        width=1280,
        height=720,
    )
    assert result.success, f"edit failed: {result.error}"
    assert result.output_path is not None and result.output_path.is_file()
    assert result.output_path.stat().st_size > 0
    assert len(result.edl) >= 1, "EDL should have caption entries"
    assert "test narration" in result.transcript.lower()

    probe = _probe_streams(str(result.output_path))
    streams = probe.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    assert v is not None and v.get("codec_name") == "h264"
    assert int(v.get("width", 0)) == 1280
    assert int(v.get("height", 0)) == 720
