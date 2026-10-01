"""External video ingest: validation, managed copy, hashing, ledger evidence."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.ingest import probe_video_file, resolution_label, sha256_file


def _app(tmp_path) -> BlueWavesApplication:
    return BlueWavesApplication(Settings(data_dir=tmp_path, youtube_upload_enabled=False))


def _make_video(path: Path, seconds: int = 2, size: str = "1280x720") -> Path:
    """Render a real, gate-passing mp4 (h264 + AAC, 30fps) with ffmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-b:v", "3000k",
        "-c:a", "aac", "-shortest",
        str(path),
    ]
    subprocess.run(command, check=True, timeout=180, capture_output=True)
    return path


def _ledger_events(app: BlueWavesApplication) -> list[dict]:
    path = Path(app.settings.data_dir) / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_ingest_happy_path(tmp_path):
    app = _app(tmp_path)
    source = _make_video(tmp_path / "src" / "explainer.mp4", seconds=2)

    asset = app.ingest_external_video(
        source, topic="Helix Codex framework explainer",
        title="Helix Codex in 6 minutes", pillar="tech", language="en",
        source="external_file",
    )

    assert asset.status.value == "awaiting_owner"
    manifest = asset.media_manifest
    assert manifest["provider"] == "external_ingest"
    assert manifest["provider_attempts"] == ["external_ingest"]
    assert manifest["scenes"] == 1
    assert manifest["chapters"] == []
    assert manifest["resolution"] == "720p"
    assert manifest["duration"] == pytest.approx(2.0, abs=0.5)
    assert manifest["size_bytes"] == source.stat().st_size
    assert manifest["source_path"] == str(source)
    assert manifest["source_sha256"] == sha256_file(source)
    assert manifest["managed_sha256"] == manifest["source_sha256"]
    assert manifest["ffprobe"]["video_codec"] == "h264"
    assert manifest["ffprobe"]["audio_codec"] == "aac"

    # Provenance points at an app-controlled artifact, not the owner's directory.
    managed = Path(manifest["video_path"])
    assert managed.is_file()
    assert managed.parent == Path(app.settings.data_dir) / "videos"
    assert source.resolve() != managed.resolve()

    # SEO draft is present and offline-safe.
    assert manifest["seo_metadata"]["title"].startswith("Helix Codex in 6 minutes")

    # Persisted and ledgered.
    stored = json.loads((Path(app.settings.data_dir) / "assets.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert stored["asset_id"] == asset.asset_id
    assert stored["status"] == "awaiting_owner"

    events = _ledger_events(app)
    ingested = [e for e in events if e["event_type"] == "external_video_ingested"]
    assert len(ingested) == 1
    assert ingested[0]["payload"]["source_sha256"] == manifest["source_sha256"]
    assert ingested[0]["payload"]["managed_sha256"] == manifest["managed_sha256"]
    assert ingested[0]["actor"] == "MIRA"

    intact, message = app.ledger.verify()
    assert intact, message


def test_ingest_missing_file(tmp_path):
    app = _app(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        app.ingest_external_video(tmp_path / "nope.mp4", topic="t")


def test_ingest_rejects_directory(tmp_path):
    app = _app(tmp_path)
    target = tmp_path / "adir.mp4"
    target.mkdir()
    with pytest.raises(ValueError, match="not a file"):
        app.ingest_external_video(target, topic="t")


def test_ingest_rejects_non_video_extension(tmp_path):
    app = _app(tmp_path)
    source = tmp_path / "notes.txt"
    source.write_text("not a video")
    with pytest.raises(ValueError, match="unsupported video type"):
        app.ingest_external_video(source, topic="t")


def test_ingest_rejects_empty_file(tmp_path):
    app = _app(tmp_path)
    source = tmp_path / "empty.mp4"
    source.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        app.ingest_external_video(source, topic="t")


def test_ingest_rejects_unprobeable_file(tmp_path):
    app = _app(tmp_path)
    source = tmp_path / "fake.mp4"
    source.write_bytes(b"\x00" * 4096)
    with pytest.raises(ValueError, match="probe failed"):
        app.ingest_external_video(source, topic="t")
    # Nothing is left behind in the managed directory.
    videos = Path(app.settings.data_dir) / "videos"
    assert not videos.exists() or not list(videos.iterdir())


def test_ingest_hash_mismatch_fails_closed(tmp_path, monkeypatch):
    """A copy that does not hash-match the source aborts the ingest."""
    app = _app(tmp_path)
    source = _make_video(tmp_path / "src" / "clip.mp4", seconds=1)

    real_sha256_file = sha256_file
    calls: list[str] = []

    def flaky(path, chunk_size=1024 * 1024):
        calls.append(str(path))
        # Second call is the managed copy: report a different digest.
        if len(calls) == 2:
            return "0" * 64
        return real_sha256_file(path, chunk_size)

    monkeypatch.setattr("blue_waves.application.sha256_file", flaky)

    with pytest.raises(ValueError, match="hash mismatch"):
        app.ingest_external_video(source, topic="t")

    videos = Path(app.settings.data_dir) / "videos"
    assert not list(videos.iterdir()), "managed copy must be removed on mismatch"
    assert not any(e["event_type"] == "external_video_ingested" for e in _ledger_events(app))


def test_probe_video_file_returns_none_for_garbage(tmp_path):
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"definitely not video")
    assert probe_video_file(bogus) is None
    assert probe_video_file(tmp_path / "absent.mp4") is None


def test_probe_video_file_reports_streams(tmp_path):
    source = _make_video(tmp_path / "clip.mp4", seconds=1)
    probe = probe_video_file(source)
    assert probe is not None
    assert probe["width"] == 1280
    assert probe["height"] == 720
    assert probe["video_codec"] == "h264"
    assert probe["audio_codec"] == "aac"
    assert probe["size_bytes"] > 0
    assert probe["duration"] == pytest.approx(1.0, abs=0.5)


@pytest.mark.parametrize(("width", "height", "expected"), [
    (3840, 2160, "4k"),
    (1920, 1080, "1080p"),
    (1080, 1920, "1080p"),
    (1280, 720, "720p"),
    (720, 1280, "720p"),
    (640, 480, "sd"),
    (0, 0, "sd"),
])
def test_resolution_label(width, height, expected):
    assert resolution_label(width, height) == expected
