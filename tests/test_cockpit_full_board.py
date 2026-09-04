"""Phase 10.6: Cockpit full control board."""
from __future__ import annotations

from pathlib import Path

from blue_waves.application import BlueWavesApplication
from blue_waves.cockpit_server import CockpitApp
from blue_waves.config import Settings


def _cockpit(tmp_path) -> CockpitApp:
    app = BlueWavesApplication(Settings(data_dir=tmp_path, youtube_upload_enabled=False))
    return CockpitApp(app)


def test_cockpit_generation_panel(tmp_path):
    """Cockpit can generate all three content types via the API layer."""
    cockpit = _cockpit(tmp_path)
    music = cockpit.generate_media("music", {
        "topic": "board music", "genre": "ambient", "mood": "calm",
        "duration_seconds": 8, "quality": "free",
    })
    assert "error" not in music, music.get("error")
    assert music["content_type"] == "music"

    podcast = cockpit.generate_media("podcast", {
        "topic": "board podcast", "script": "Host: Hello. Guest: Hi there. " * 3,
        "duration_seconds": 10, "quality": "free",
    })
    assert "error" not in podcast, podcast.get("error")
    assert podcast["content_type"] == "podcast"

    video = cockpit.generate_media("video", {
        "topic": "board video", "prompt": "title card", "duration": 2, "quality": "draft",
    })
    assert "error" not in video, video.get("error")
    assert video["content_type"] == "video"

    library = cockpit.get_library()
    assert library["count"] >= 3


def test_cockpit_crew_monitor_includes_shepo(tmp_path):
    """Crew panel shows SHEPO with the finance role."""
    cockpit = _cockpit(tmp_path)
    crew = cockpit.get_crew()
    by_id = {a["id"]: a for a in crew["agents"]}
    assert "shepo" in by_id, f"missing SHEPO in {[a['id'] for a in crew['agents']]}"
    assert "Finance" in by_id["shepo"]["role"]
    assert len(crew["agents"]) >= 9


def test_cockpit_finance_panel_shows_real_costs(tmp_path):
    """Finance panel surfaces non-zero tracked costs and SHEPO projections."""
    cockpit = _cockpit(tmp_path)
    cockpit._app.finance.log_cost("suno_api", "music", "music-board-1", credits=1)
    cockpit._app.finance.log_cost("kling", "video", "video-board-1", credits=1)
    plan = cockpit.get_finance_plan()
    assert "shepo_report" in plan
    shepo = plan["shepo_report"]
    assert shepo["agent"] == "SHEPO"
    assert shepo["weekly_cost_cents"] > 0
    assert shepo["content_costs"]["music_cents"] > 0
    assert shepo["provider_comparison"], "provider ROI table should not be empty"
    assert "revenue_projection" in shepo
    assert "break_even_analysis" in shepo


def test_cockpit_review_panel_quality_breakdown(tmp_path):
    """Review panel exposes a quality score breakdown per asset."""
    cockpit = _cockpit(tmp_path)
    created = cockpit.generate_media("music", {
        "topic": "review track", "duration_seconds": 8, "quality": "free",
    })
    assert "error" not in created
    asset_id = created["asset_id"]
    breakdown = cockpit.get_quality_breakdown(asset_id)
    assert breakdown["asset_id"] == asset_id
    assert breakdown["content_type"] == "music"
    assert "score" in breakdown and "issues" in breakdown
    assert breakdown["score"] >= 0.0

    assert cockpit.get_video_use_status()["enabled"] in (True, False)

    approvals = cockpit.get_pending_approvals()
    assert any(item["asset_id"] == asset_id for item in approvals)
