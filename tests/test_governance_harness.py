from __future__ import annotations

import pytest

from blue_waves.governance import Governance, GovernanceViolation, Policy
from blue_waves.models import AssetStatus, Language, MusicAsset, PodcastAsset


def test_autonomous_generation_blocks_when_video_cap_reached():
    governance = Governance(Policy(max_weekly_videos=5))
    with pytest.raises(GovernanceViolation, match="weekly video cap"):
        governance.assert_autonomous_generation_allowed("video", weekly_count=5, estimated_cents=0)


def test_autonomous_generation_blocks_when_music_cap_reached():
    governance = Governance(Policy(max_weekly_music=10))
    with pytest.raises(GovernanceViolation, match="weekly music cap"):
        governance.assert_autonomous_generation_allowed("music", weekly_count=10, estimated_cents=0)


def test_autonomous_generation_blocks_when_podcast_cap_reached():
    governance = Governance(Policy(max_weekly_podcasts=3))
    with pytest.raises(GovernanceViolation, match="weekly podcast cap"):
        governance.assert_autonomous_generation_allowed("podcast", weekly_count=3, estimated_cents=0)


def test_autonomous_generation_blocks_when_budget_exceeded():
    governance = Governance(Policy(monthly_cloud_cents=100))
    with pytest.raises(GovernanceViolation, match="cloud budget blocked"):
        governance.assert_autonomous_generation_allowed("video", weekly_count=0, estimated_cents=200)


def test_autonomous_generation_allows_within_limits():
    governance = Governance(Policy(max_weekly_videos=10, monthly_cloud_cents=100))
    governance.assert_autonomous_generation_allowed("video", weekly_count=5, estimated_cents=10)


def test_quality_gate_approves_above_threshold():
    governance = Governance(Policy(quality_gate_threshold=0.7))
    assert governance.assert_quality_gate(0.8) is True
    assert governance.assert_quality_gate(1.0) is True


def test_quality_gate_rejects_below_threshold():
    governance = Governance(Policy(quality_gate_threshold=0.7))
    assert governance.assert_quality_gate(0.5) is False
    assert governance.assert_quality_gate(0.0) is False


def test_provider_fallback_returns_correct_provider():
    governance = Governance(Policy(provider_fallback_enabled=True))
    assert governance.assert_provider_fallback("kling") == "seedance"
    assert governance.assert_provider_fallback("suno_api") == "ace_step"
    assert governance.assert_provider_fallback("kokoro") == "edge_tts"
    assert governance.assert_provider_fallback("unknown") == "ken_burns"


def test_provider_fallback_disabled_raises():
    governance = Governance(Policy(provider_fallback_enabled=False))
    with pytest.raises(GovernanceViolation, match="fallback is disabled"):
        governance.assert_provider_fallback("kling")


def test_publishable_music_blocks_when_not_approved():
    governance = Governance(Policy())
    asset = MusicAsset(
        asset_id="m1", tenant_id="bluewaves", title="test",
        genre="pop", mood="happy", duration_seconds=180,
        language=Language.EN, status=AssetStatus.AWAITING_OWNER, prompt="test",
    )
    with pytest.raises(GovernanceViolation, match="not approved"):
        governance.assert_publishable_music(asset, weekly_count=0)


def test_publishable_music_blocks_when_weekly_cap_reached():
    governance = Governance(Policy(max_weekly_music=2))
    asset = MusicAsset(
        asset_id="m1", tenant_id="bluewaves", title="test",
        genre="pop", mood="happy", duration_seconds=180,
        language=Language.EN, status=AssetStatus.APPROVED, prompt="test",
    )
    asset.approval_id = "approval-m1"
    with pytest.raises(GovernanceViolation, match="weekly music cap"):
        governance.assert_publishable_music(asset, weekly_count=2)


def test_publishable_music_allows_within_limits():
    governance = Governance(Policy(max_weekly_music=10))
    asset = MusicAsset(
        asset_id="m1", tenant_id="bluewaves", title="test",
        genre="pop", mood="happy", duration_seconds=180,
        language=Language.EN, status=AssetStatus.APPROVED, prompt="test",
    )
    asset.approval_id = "approval-m1"
    governance.assert_publishable_music(asset, weekly_count=5)


def test_publishable_podcast_blocks_when_not_approved():
    governance = Governance(Policy())
    asset = PodcastAsset(
        asset_id="p1", tenant_id="bluewaves", title="test",
        topic="test", format="dialogue", language=Language.EN,
        duration_target_seconds=1800, status=AssetStatus.AWAITING_OWNER,
        host_voice="host",
    )
    with pytest.raises(GovernanceViolation, match="not approved"):
        governance.assert_publishable_podcast(asset, weekly_count=0)


def test_publishable_podcast_blocks_when_duration_exceeds_limit():
    governance = Governance(Policy(max_podcast_duration_minutes=30))
    asset = PodcastAsset(
        asset_id="p1", tenant_id="bluewaves", title="test",
        topic="test", format="dialogue", language=Language.EN,
        duration_target_seconds=3600, status=AssetStatus.APPROVED,
        host_voice="host",
    )
    asset.approval_id = "approval-p1"
    with pytest.raises(GovernanceViolation, match="exceeds max duration"):
        governance.assert_publishable_podcast(asset, weekly_count=0)


def test_publishable_podcast_allows_within_limits():
    governance = Governance(Policy(max_podcast_duration_minutes=60, max_weekly_podcasts=10))
    asset = PodcastAsset(
        asset_id="p1", tenant_id="bluewaves", title="test",
        topic="test", format="dialogue", language=Language.EN,
        duration_target_seconds=1800, status=AssetStatus.APPROVED,
        host_voice="host",
    )
    asset.approval_id = "approval-p1"
    governance.assert_publishable_podcast(asset, weekly_count=5)


def test_generation_allowed_allows_zero_cost():
    governance = Governance(Policy(monthly_cloud_cents=0))
    governance.assert_generation_allowed("video", "ace_step", estimated_cents=0)


def test_generation_allowed_blocks_positive_cost_when_budget_zero():
    governance = Governance(Policy(monthly_cloud_cents=0))
    with pytest.raises(GovernanceViolation, match="cloud budget blocked"):
        governance.assert_generation_allowed("video", "kling", estimated_cents=10)
