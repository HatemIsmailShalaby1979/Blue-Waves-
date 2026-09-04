"""Phase C: native Kling contract parsing + last-frame helper (offline)."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from blue_waves.providers import (
    KlingVideoProvider,
    _kling_parse_status,
    _kling_parse_task,
)
from blue_waves.video_engine import VideoEngine


def test_parse_task_official_shape():
    assert _kling_parse_task({"code": 0, "data": {"task_id": "abc123"}}) == "abc123"


def test_parse_task_legacy_shape():
    assert _kling_parse_task({"task_id": "xyz"}) == "xyz"
    assert _kling_parse_task({"id": "qrs"}) == "qrs"


def test_parse_task_missing_raises():
    from blue_waves.providers import ProviderUnavailable
    with pytest.raises(ProviderUnavailable):
        _kling_parse_task({"code": 0})


def test_parse_status_completed_shapes():
    state, url = _kling_parse_status(
        {"code": 0, "data": {"task_status": "succeed",
                             "task_result": {"videos": [{"url": "https://cdn/x.mp4"}]}}})
    assert state == "completed" and url == "https://cdn/x.mp4"
    state, _ = _kling_parse_status({"status": "completed", "video": {"url": "https://cdn/y.mp4"}})
    assert state == "completed"


def test_parse_status_running_and_failed():
    state, url = _kling_parse_status({"data": {"task_status": "processing"}})
    assert state == "running" and url is None
    from blue_waves.providers import ProviderUnavailable
    with pytest.raises(ProviderUnavailable):
        _kling_parse_status({"data": {"task_status": "failed", "fail_reason": "no funds"}})


def test_kling_requires_key():
    from blue_waves.providers import ProviderUnavailable
    provider = KlingVideoProvider(api_key=None)
    with pytest.raises(ProviderUnavailable):
        provider.generate(prompt="x", duration=5)
    with pytest.raises(ProviderUnavailable):
        provider.generate_from_image(b"fake", prompt="x")


def test_kling_supports_image_to_video():
    provider = KlingVideoProvider(api_key="k")
    assert provider.supports_image_to_video is True
    assert provider.provides_narration is False


def test_extract_last_frame_from_synthetic_clip(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=320x240:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True, timeout=60, capture_output=True,
    )
    frame = VideoEngine._extract_last_frame(clip)
    assert frame[:2] == b"\xff\xd8"  # JPEG magic
    assert len(frame) > 1000
