"""Cockpit wiring for external video ingest, review and the publish flip."""
from __future__ import annotations

import json
import subprocess
import threading
import urllib.request
from http.server import HTTPServer
from typing import TYPE_CHECKING

from test_unlisted_publish import FakeYouTubeUploadService

from blue_waves.application import BlueWavesApplication
from blue_waves.cockpit_server import CockpitApp, CockpitHTTPHandler
from blue_waves.config import Settings

if TYPE_CHECKING:
    from pathlib import Path


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


class _LiveCockpit:
    """A real HTTP server on an ephemeral port, so route wiring is actually exercised."""

    def __init__(self, app: BlueWavesApplication) -> None:
        handler = type("_Handler", (CockpitHTTPHandler,), {})
        handler.app = app
        handler.cockpit = CockpitApp(app)
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path, timeout=60) as response:
            return json.loads(response.read())

    def post(self, path: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload or {}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())


def test_cockpit_ingest_route(tmp_path):
    app = _app(tmp_path)
    cockpit = CockpitApp(app)
    source = _make_video(tmp_path / "src" / "explainer.mp4")

    result = cockpit.ingest_video({
        "path": str(source), "topic": "Helix Codex framework explainer",
        "title": "Helix Codex in 6 minutes", "pillar": "tech", "language": "en",
    })

    assert "error" not in result, result.get("error")
    assert result["content_type"] == "video"
    assert result["status"] == "awaiting_owner"
    assert result["media_manifest"]["provider"] == "external_ingest"
    assert result["resolved_path"] == str(source)
    assert result["asset_id"] in app.assets


def test_cockpit_ingest_route_rejects_bad_path(tmp_path):
    cockpit = CockpitApp(_app(tmp_path))
    assert "error" in cockpit.ingest_video({})
    assert "error" in cockpit.ingest_video({"path": str(tmp_path / "missing.mp4")})
    assert "error" in cockpit.ingest_video({"path": str(tmp_path)})

    text = tmp_path / "notes.txt"
    text.write_text("nope")
    assert "error" in cockpit.ingest_video({"path": str(text)})


def test_cockpit_review_payload_fields(tmp_path):
    app = _app(tmp_path)
    cockpit = CockpitApp(app)
    source = _make_video(tmp_path / "src" / "clip.mp4")
    ingested = cockpit.ingest_video({"path": str(source), "topic": "t", "title": "T"})

    review = cockpit.get_review(ingested["asset_id"])

    assert review["media_url"] == f"/media/video/{ingested['asset_id']}"
    assert review["media_exists"] is True
    assert review["youtube_embed_url"] is None
    assert review["privacy_status"] is None
    assert review["can_go_public"] is False
    assert review["seo_metadata"]["title"] == "T"
    assert review["source_sha256"] == review["managed_sha256"]
    assert review["resolution"] == "720p"
    assert "error" in cockpit.get_review("nope")


def test_cockpit_metadata_save(tmp_path):
    app = _app(tmp_path)
    cockpit = CockpitApp(app)
    source = _make_video(tmp_path / "src" / "clip.mp4")
    ingested = cockpit.ingest_video({"path": str(source), "topic": "t"})

    result = cockpit.save_review_metadata(ingested["asset_id"], {
        "title": "Edited via cockpit", "description": "Body text", "tags": "alpha, beta ,gamma",
    })

    assert result["seo_metadata"]["title"] == "Edited via cockpit"
    assert result["seo_metadata"]["tags"] == ["alpha", "beta", "gamma"]
    assert cockpit.get_review(ingested["asset_id"])["seo_metadata"]["description"] == "Body text"


def test_cockpit_go_public_route_with_fake_service(tmp_path):
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    cockpit = CockpitApp(app)
    source = _make_video(tmp_path / "src" / "clip.mp4")
    asset_id = cockpit.ingest_video({"path": str(source), "topic": "t", "title": "T"})["asset_id"]

    app.owner_approve(app.get_asset(asset_id))
    uploaded = cockpit.upload_unlisted(asset_id)
    assert uploaded["privacy_status"] == "unlisted"

    review = cockpit.get_review(asset_id)
    assert review["status"] == "uploaded_unlisted"
    assert review["youtube_embed_url"] == "https://www.youtube.com/embed/fake-video-1"
    assert review["can_go_public"] is True

    published = cockpit.go_public(asset_id)
    assert published["privacy_status"] == "public"
    assert app.get_asset(asset_id).status.value == "published"


def test_cockpit_upload_unlisted_surfaces_governance_error(tmp_path):
    app = _app(tmp_path, FakeYouTubeUploadService())
    cockpit = CockpitApp(app)
    source = _make_video(tmp_path / "src" / "clip.mp4")
    asset_id = cockpit.ingest_video({"path": str(source), "topic": "t"})["asset_id"]

    result = cockpit.upload_unlisted(asset_id)

    assert "error" in result
    assert "owner-approved" in result["error"]


def test_cockpit_go_public_surfaces_private_lock(tmp_path):
    fake = FakeYouTubeUploadService(status_after_update="private")
    app = _app(tmp_path, fake)
    cockpit = CockpitApp(app)
    source = _make_video(tmp_path / "src" / "clip.mp4")
    asset_id = cockpit.ingest_video({"path": str(source), "topic": "t"})["asset_id"]
    app.owner_approve(app.get_asset(asset_id))
    cockpit.upload_unlisted(asset_id)

    result = cockpit.go_public(asset_id)

    assert "error" in result
    assert "private-lock" in result["error"]
    assert app.get_asset(asset_id).status.value == "uploaded_unlisted"


def test_oauth_callback_route_exists_on_cockpit(tmp_path, monkeypatch):
    """The callback must be served by the cockpit handler (8420), not only the old service."""
    app = _app(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_callback(code: str, state: str) -> dict:
        calls.append((code, state))
        return {"provider": "youtube", "connected": True, "scopes": ["youtube.force-ssl"]}

    monkeypatch.setattr(app, "youtube_oauth_callback", fake_callback)

    live = _LiveCockpit(app)
    try:
        data = live.get("/oauth/youtube/callback?code=abc123&state=st456")
    finally:
        live.close()

    assert data["connected"] is True
    assert calls == [("abc123", "st456")]


def test_cockpit_new_routes_over_http(tmp_path):
    """End-to-end over the wire: ingest → metadata → upload unlisted → go public."""
    fake = FakeYouTubeUploadService()
    app = _app(tmp_path, fake)
    source = _make_video(tmp_path / "src" / "clip.mp4")

    live = _LiveCockpit(app)
    try:
        ingested = live.post("/api/ingest/video", {"path": str(source), "topic": "Helix Codex", "title": "T"})
        assert ingested["status"] == "awaiting_owner"
        asset_id = ingested["asset_id"]

        app.owner_approve(app.get_asset(asset_id))

        review = live.get(f"/api/review/{asset_id}")
        assert review["asset_id"] == asset_id

        saved = live.post(f"/api/review/{asset_id}/metadata", {"title": "Wire title", "tags": "a,b"})
        assert saved["seo_metadata"]["title"] == "Wire title"

        uploaded = live.post(f"/api/upload-unlisted/{asset_id}")
        assert uploaded["privacy_status"] == "unlisted"

        published = live.post(f"/api/go-public/{asset_id}")
        assert published["privacy_status"] == "public"
        assert app.get_asset(asset_id).status.value == "published"
    finally:
        live.close()

    upload = next(call for call in fake.calls if call["method"] == "upload_video")
    assert upload["privacy_status"] == "unlisted"
    assert upload["title"] == "Wire title"
    assert upload["tags"] == ["a", "b"]
