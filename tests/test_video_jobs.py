"""Background video jobs + multi-scene assembly (fast paths only)."""
from __future__ import annotations

import time

import pytest

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.dialogue import build_narration
from blue_waves.jobs import JobManager
from blue_waves.video_engine import split_narration_sections


def _app(tmp_path) -> BlueWavesApplication:
    return BlueWavesApplication(Settings(data_dir=tmp_path, youtube_upload_enabled=False))


def test_split_narration_sections_balanced():
    narration = build_narration("how batteries work", 180)
    sections = split_narration_sections(narration, 6)
    assert len(sections) == 6
    counts = [len(s.split()) for s in sections]
    assert all(c > 20 for c in counts), counts
    # All words preserved (each sentence ends with a period).
    assert sum(counts) >= len(narration.split()) - 6


def test_split_narration_single_scene():
    sections = split_narration_sections("Short text.", 1)
    assert sections == ["Short text."]


def test_submit_video_job_validation(tmp_path):
    app = _app(tmp_path)
    with pytest.raises(ValueError):
        app.submit_video_job(topic="", prompt="x", duration=180)
    with pytest.raises(ValueError):
        app.submit_video_job(topic="t", prompt="x", duration=20)
    with pytest.raises(ValueError):
        app.submit_video_job(topic="t", prompt="x", duration=601)


def test_job_manager_lifecycle():
    mgr = JobManager()
    job = mgr.submit_video(topic="t", prompt="p", duration=120)
    assert job.status == "queued"
    assert mgr.get(job.job_id).job_id == job.job_id
    assert any(j.job_id == job.job_id for j in mgr.list_jobs())
    assert mgr.get("job-missing") is None


def test_background_short_video_job_completes(tmp_path):
    """End-to-end job path with a tiny render (exercises worker + persist)."""
    app = _app(tmp_path)
    job = app.submit_video_job(topic="quick job test", prompt="title card",
                               duration=60, quality="draft")
    assert job.status in ("queued", "running")
    deadline = time.time() + 540
    while time.time() < deadline:
        current = app.get_video_job(job.job_id)
        if current.status in ("completed", "failed"):
            break
        time.sleep(5)
    final = app.get_video_job(job.job_id)
    assert final.status == "completed", f"job failed: {final.error}"
    assert final.progress == 100.0
    assert final.asset_id in app.assets
