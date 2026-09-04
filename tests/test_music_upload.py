"""Phase A: owner-supplied MP3/WAV ingest (Suno web export, free-library music)."""
from __future__ import annotations

import subprocess
import wave

import pytest

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.cockpit_server import CockpitApp


def _app(tmp_path) -> BlueWavesApplication:
    return BlueWavesApplication(Settings(data_dir=tmp_path, youtube_upload_enabled=False))


def _tone_wav(seconds: int = 3, rate: int = 44100) -> bytes:
    import io
    import math
    import struct
    frames = b"".join(
        struct.pack("<hh", *[int(12000 * math.sin(2 * math.pi * 440 * t / rate))] * 2)
        for t in range(seconds * rate)
    )
    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return stream.getvalue()


def _probe(path: str) -> dict:
    import json
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels",
         "-show_entries", "format=duration", "-of", "json", path],
        check=True, timeout=30, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def test_upload_music_mastered_to_spec(tmp_path):
    app = _app(tmp_path)
    asset = app.import_uploaded_music(
        filename="sunset-drive.mp3", data=_tone_wav(),
        title="Sunset Drive", genre="synthwave", mood="energetic",
        source="youtube_audio_library", license_note="YT Audio Library, cleared",
    )
    assert asset.status.value == "awaiting_owner"
    assert asset.provider == "manual_upload"
    assert asset.duration_seconds == 3
    assert asset.metadata["source"] == "youtube_audio_library"
    assert asset.metadata["source_sha256"]
    probe = _probe(asset.audio_path)
    stream = (probe.get("streams") or [{}])[0]
    assert int(stream.get("sample_rate", 0)) == 48000
    assert int(stream.get("channels", 0)) == 2


def test_upload_rejects_garbage_and_empty(tmp_path):
    app = _app(tmp_path)
    with pytest.raises(ValueError):
        app.import_uploaded_music(filename="empty.mp3", data=b"")
    with pytest.raises(ValueError):
        app.import_uploaded_music(filename="notes.txt", data=b"not audio at all" * 100)
    with pytest.raises(ValueError):
        app.import_uploaded_music(filename="fake.mp3", data=b"\x00" * 5000)


def test_upload_via_cockpit_multipart(tmp_path):
    app = _app(tmp_path)
    cockpit = CockpitApp(app)
    boundary = "TESTBOUNDARY123"
    audio = _tone_wav(seconds=2)
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nCockpit Track\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"source\"\r\n\r\nsuno_web\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"track.mp3\"\r\n"
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    result = cockpit.upload_music(f"multipart/form-data; boundary={boundary}", body)
    assert "error" not in result, result.get("error")
    assert result["content_type"] == "music"
    assert result["status"] == "awaiting_owner"
    assert result["metadata"]["source"] == "suno_web"


def test_upload_multipart_missing_file(tmp_path):
    cockpit = CockpitApp(_app(tmp_path))
    result = cockpit.upload_music(
        "multipart/form-data; boundary=B",
        b"--B\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nx\r\n--B--\r\n",
    )
    assert "error" in result
