"""Phase 10.5: SHEPO finance — real costs, revenue, break-even."""
from __future__ import annotations

from blue_waves.agents import AGENTS
from blue_waves.finance import FinanceEngine


def test_shepo_agent_exists():
    shepo = next((a for a in AGENTS if a.agent_id == "shepo"), None)
    assert shepo is not None, "SHEPO agent missing from roster"
    assert "Finance" in shepo.role
    assert "track real costs per generation" in shepo.can
    assert "move money" in shepo.cannot


def test_shepo_tracks_real_costs():
    """SHEPO logs actual provider costs, not zero."""
    finance = FinanceEngine()
    finance.log_cost("suno_api", "music", "music-1", credits=1)
    finance.log_cost("elevenlabs_tts", "podcast", "pod-1", char_count=1500)
    finance.log_cost("edge_tts", "podcast", "pod-2", credits=1)
    totals = finance.get_total_costs()
    assert totals.get("suno_api", 0) > 0, "suno cost should be non-zero"
    assert totals.get("elevenlabs_tts", 0) > 0, "elevenlabs cost should scale with chars"
    assert finance.get_content_costs("music") > 0
    assert finance.get_weekly_costs() > 0
    report = finance.get_shepo_report()
    assert report["agent"] == "SHEPO"
    assert report["cost_count"] == 3
    assert report["content_costs"]["music_cents"] > 0


def test_shepo_projects_revenue():
    """SHEPO projects monthly revenue based on CPM and upload frequency."""
    finance = FinanceEngine()
    finance.log_cost("suno_api", "music", "music-1", credits=1)
    proj = finance.project_monthly_revenue(views_per_video=1000, cpm=4.0, upload_frequency=12)
    assert proj["views_per_video"] == 1000
    assert proj["cpm"] == 4.0
    assert proj["upload_frequency"] == 12
    # 1000 views @ $4 CPM = $4/video * 12 = $48.
    assert proj["monthly_revenue_cents"] == 4800
    assert "net_profit_cents" in proj
    assert "profitable" in proj


def test_shepo_break_even():
    """SHEPO calculates a break-even point."""
    finance = FinanceEngine()
    finance.log_cost("kling", "video", "vid-1", credits=1)
    be = finance.calculate_break_even(monthly_budget_cents=5000,
                                      views_per_video=500, upload_frequency=15)
    assert be["monthly_cost_cents"] >= 5000
    assert be["required_views_per_video"] > 0
    assert "months_to_break_even" in be
    assert "break_even_feasible" in be
    runway = finance.get_runway(monthly_budget_cents=5000)
    assert runway["monthly_cost_cents"] == 5000
