"""Unlisted-upload → owner-review → public flow, and the preflight evidence.

Every path here is fail-closed: a failure at any step must leave the asset
non-public and leave a ledger record behind.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.governance import GovernanceViolation


class FakeYouTubeUploadService:
    """Records calls; can be told to fail the upload or refuse the privacy flip."""

    def __init__(self, fail_upload: bool = False, fail_update: bool = False,
                 status_after_update: str = "public") -> None:
        self.calls: list[dict] = []
        self.fail_upload = fail_upload
        self.fail_update = fail_update
        self.status_after_update = status_after_update
        self._counter = 0

    def upload_video(self, video_path, title, description="", tags=None, category_id="27",
                     privacy_status="private") -> dict:
        self.calls.append({
            "method": "upload_video", "privacy_status": privacy_status, "title": title,
            "description": description, "tags": list(tags or []), "category_id": category_id,
        })
        if self.fail_upload:
            raise RuntimeError("upload boom")
        self._counter += 1
        video_id = f"fake-video-{self._counter}"
        return {
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "title": title,
            "privacy_status": privacy_status,
        }

    def update_video_privacy(self, video_id: str, privacy_status: str) -> dict:
        self.calls.append({"method": "update_video_privacy", "video_id": video_id,
                           "privacy_status": privacy_status})
        if self.fail_update:
            raise RuntimeError("update boom")
        return {"video_id": video_id, "privacy_status": privacy_status}

    def get_video_status(self, video_id: str) -> dict:
        self.calls.append({"method": "get_video_status", "video_id": video_id})
        return {"video_id": video_id, "found": True,
                "privacy_status": self.status_after_update, "upload_status": "processed"}


def _app(tmp_path, fake: FakeYouTubeUploadService | None = None) -> BlueWavesApplication:
    app = BlueWavesApplication(Settings(data_dir=tmp_path, youtube_upload_enabled=True))
    if fake is not None:
        app._youtube_service = fake  # noqa: SLF001 - deliberate test injection point
    return app


def _make_video(path: Path, seconds: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-b:v", "3000k",
        "-c:a", "aac", "-shortest", str(path),
    ], check=True, timeout=180, capture_output=True)
    return path


def _approved_asset(app: BlueWavesApplication, tmp_path: Path, name: str = "clip.mp4"):
    asset = app.ingest_external_video(
        _make_video(tmp_path / "src" / name), topic="Helix Codex framework explainer",
        title="Helix Codex in 6 minutes", pillar="tech",
    )
    app.owner_approve(asset)
    assert asset.status.value == "approved"
    return asset


def _events(app: BlueWavesApplication) -> list[dict]:
    lines = (Path(app.settings.data_dir) / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _event_types(app: BlueWavesApplication) -> list[str]:
    return [event["event_type"] for event in _events(app)]


def test_unlisted_happy_path(tmp_path):
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)

    result = app.upload_unlisted(asset.asset_id)

    assert result["privacy_status"] == "unlisted"
    assert result["youtube_video_id"] == "fake-video-1"
    assert asset.status.value == "uploaded_unlisted"
    assert asset.media_manifest["privacy_status"] == "unlisted"
    assert asset.media_manifest["youtube_url"] == "https://www.youtube.com/watch?v=fake-video-1"

    uploads = [call for call in fake.calls if call["method"] == "upload_video"]
    assert len(uploads) == 1
    assert uploads[0]["privacy_status"] == "unlisted"
    assert uploads[0]["title"] == "Helix Codex in 6 minutes"

    assert "video_uploaded_unlisted" in _event_types(app)
    intact, message = app.ledger.verify()
    assert intact, message


def test_upload_requires_owner_approval(tmp_path):
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    asset = app.ingest_external_video(
        _make_video(tmp_path / "src" / "clip.mp4"), topic="t", title="T")
    assert asset.status.value == "awaiting_owner"

    with pytest.raises(GovernanceViolation, match="owner-approved"):
        app.upload_unlisted(asset.asset_id)

    assert asset.status.value == "awaiting_owner"
    assert not fake.calls


def test_upload_requires_approval_record(tmp_path):
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)
    asset.approval_id = None  # simulate a lost approval record

    with pytest.raises(GovernanceViolation, match="approval record"):
        app.upload_unlisted(asset.asset_id)
    assert not fake.calls


def test_upload_weekly_cap_enforced(tmp_path):
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)
    for index in range(app.policy.max_weekly_publishes):
        app.add_content_request("video", f"queued {index}")

    with pytest.raises(GovernanceViolation, match="weekly publish cap"):
        app.upload_unlisted(asset.asset_id)
    assert not fake.calls


def test_upload_failure_is_fail_closed(tmp_path):
    fake = FakeYouTubeUploadService(fail_upload=True)
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)

    with pytest.raises(RuntimeError, match="upload boom"):
        app.upload_unlisted(asset.asset_id)

    assert asset.status.value == "approved"
    assert "youtube_video_id" not in asset.media_manifest
    events = _events(app)
    assert events[-1]["event_type"] == "video_upload_failed"
    assert "video_uploaded_unlisted" not in _event_types(app)


def test_go_public_happy_path(tmp_path):
    fake = FakeYouTubeUploadService(status_after_update="public")
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)
    app.upload_unlisted(asset.asset_id)

    result = app.go_public(asset.asset_id, approver="hatem")

    assert result["privacy_status"] == "public"
    assert asset.status.value == "published"
    assert asset.media_manifest["privacy_status"] == "public"
    methods = [call["method"] for call in fake.calls]
    assert methods == ["upload_video", "update_video_privacy", "get_video_status"]
    assert _event_types(app)[-1] == "video_published_public"
    intact, message = app.ledger.verify()
    assert intact, message


def test_go_public_denied_for_non_owner(tmp_path):
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)
    app.upload_unlisted(asset.asset_id)

    with pytest.raises(GovernanceViolation, match="human owner"):
        app.go_public(asset.asset_id, approver="intruder")

    assert asset.status.value == "uploaded_unlisted"
    assert not any(call["method"] == "update_video_privacy" for call in fake.calls)


def test_go_public_denied_before_upload(tmp_path):
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)

    with pytest.raises(GovernanceViolation, match="uploaded_unlisted"):
        app.go_public(asset.asset_id, approver="hatem")

    assert asset.status.value == "approved"
    assert not any(call["method"] == "update_video_privacy" for call in fake.calls)


def test_go_public_private_lock_is_fail_closed(tmp_path):
    """Update reports success but the video stays private → suspected lock."""
    fake = FakeYouTubeUploadService(status_after_update="private")
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)
    app.upload_unlisted(asset.asset_id)

    with pytest.raises(GovernanceViolation, match="private-lock"):
        app.go_public(asset.asset_id, approver="hatem")

    assert asset.status.value == "uploaded_unlisted"
    assert asset.media_manifest["privacy_status"] == "unlisted"
    assert _event_types(app)[-1] == "go_public_failed"
    assert "video_published_public" not in _event_types(app)


def test_go_public_update_error_is_fail_closed(tmp_path):
    fake = FakeYouTubeUploadService(fail_update=True)
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)
    app.upload_unlisted(asset.asset_id)

    with pytest.raises(GovernanceViolation, match="privacy flip failed"):
        app.go_public(asset.asset_id, approver="hatem")

    assert asset.status.value == "uploaded_unlisted"
    assert _event_types(app)[-1] == "go_public_failed"


def test_seo_metadata_edit_persists_and_is_uploaded(tmp_path):
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    asset = _approved_asset(app, tmp_path)

    app.update_seo_metadata(asset.asset_id, title="Edited title",
                            description="Edited description",
                            tags=["helix", "codex", "agents"])

    stored_lines = (Path(app.settings.data_dir) / "assets.jsonl").read_text(encoding="utf-8").splitlines()
    latest = json.loads(stored_lines[-1])
    seo = latest["media_manifest"]["seo_metadata"]
    assert seo["title"] == "Edited title"
    assert seo["description"] == "Edited description"
    assert seo["tags"] == ["helix", "codex", "agents"]
    assert seo["category_id"] == "27"
    assert "seo_metadata_updated" in _event_types(app)

    app.upload_unlisted(asset.asset_id)
    upload = next(call for call in fake.calls if call["method"] == "upload_video")
    assert upload["title"] == "Edited title"
    assert upload["description"] == "Edited description"
    assert upload["tags"] == ["helix", "codex", "agents"]


def test_preflight_reports_scope_gap_and_reference_visibility(tmp_path, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(app, "_oembed_is_public",
                        lambda video_id: {"ok": True, "public": True, "status_code": 200})
    video = _make_video(tmp_path / "src" / "clip.mp4", seconds=1)

    report = app.preflight_youtube_publish(video)

    assert report["reference_video_public"] is True
    assert report["force_ssl_scope_granted"] is False
    assert report["ok"] is False
    assert report["quota"]["videos_insert_units"] == 1600
    assert report["quota"]["uploads_per_day"] == 6
    assert report["file"]["exists"] is True
    assert report["file"]["sha256"]
    assert report["file"]["ffprobe"]["video_codec"] == "h264"


def test_preflight_detects_force_ssl_scope(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app.connections.save("youtube", {"scopes": ["youtube.upload", "youtube.force-ssl"]})
    monkeypatch.setattr(app, "_oembed_is_public",
                        lambda video_id: {"ok": False, "public": False, "status_code": 401})

    report = app.preflight_youtube_publish()

    assert report["force_ssl_scope_granted"] is True
    assert report["reference_video_public"] is False
    assert report["video_path"] is None
    assert "file" not in report
