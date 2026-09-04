"""Phase 10.4: Quality gate real metrics."""
from __future__ import annotations

import wave
from pathlib import Path

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.content_quality_scorer import ContentQualityScorer
from blue_waves.models import AssetStatus, MusicAsset, PodcastAsset


def _app(tmp_path) -> BlueWavesApplication:
    return BlueWavesApplication(Settings(data_dir=tmp_path, youtube_upload_enabled=False))


def _silent_wav(path: Path, seconds: int = 4, rate: int = 48000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = seconds * rate
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames * 2)
    return path


def test_quality_gate_rejects_missing_preview(tmp_path):
    """Gate rejects video with no preview file."""
    app = _app(tmp_path)
    asset = app.generate_video(topic="gate test", prompt="gate test", duration=2, quality="draft")
    assert asset is not None
    check = app.quality_gates.check_media_asset(asset, None, "video")
    assert not check.passed
    assert any("preview" in issue.lower() for issue in check.issues)


def test_quality_gate_rejects_duration_mismatch_music(tmp_path):
    """Gate rejects music whose file length differs from the requested runtime."""
    app = _app(tmp_path)
    asset = app.generate_music(topic="mismatch", duration_seconds=10, quality="free")
    assert asset is not None
    # Lie about the requested duration: file is ~10s but asset claims 120s.
    asset.duration_seconds = 120
    check = app.quality_gates.check_media_asset(asset, asset.audio_path, "music")
    assert not check.passed
    assert any("duration" in issue.lower() for issue in check.issues)


def test_quality_gate_rejects_silent_podcast(tmp_path):
    """Gate rejects a fully silent podcast (speech ratio too low)."""
    app = _app(tmp_path)
    silent = _silent_wav(tmp_path / "silent.wav", seconds=4)
    asset = PodcastAsset(
        asset_id="podcast-silent",
        tenant_id="bluewaves",
        title="Silent",
        topic="silence",
        host_voice="host",
        language="en",
        duration_target_seconds=4,
        status=AssetStatus.AWAITING_OWNER,
        script="nothing to hear",
        audio_path=str(silent),
    )
    check = app.quality_gates.check_media_asset(asset, str(silent), "podcast")
    assert not check.passed, "silent podcast should fail the gate"
    assert any("silent" in issue.lower() for issue in check.issues)

    scorer = ContentQualityScorer()
    report = scorer.analyze_podcast(silent, expected_duration=4)
    assert report.metrics.get("speech_ratio", 1.0) < 0.6
    assert report.score < 1.0


def test_quality_scorer_rejects_unprobable_file(tmp_path):
    """Scorer returns 0 for a file ffprobe cannot parse."""
    scorer = ContentQualityScorer()
    bogus = tmp_path / "bogus.wav"
    bogus.write_bytes(b"not-a-media-file")
    report = scorer.analyze_music(bogus, expected_duration=10)
    assert report.score == 0.0
    assert report.issues
