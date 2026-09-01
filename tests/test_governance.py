from pathlib import Path

import pytest

from blue_waves.governance import Governance, GovernanceViolation, Policy
from blue_waves.models import AssetStatus, ContentAsset, Language


def asset(status=AssetStatus.AWAITING_OWNER):
    return ContentAsset(
        asset_id="asset-1",
        tenant_id="bluewaves",
        topic="topic",
        pillar="the_operators_craft",
        language=Language.EN,
        status=status,
        body="lesson",
    )


def test_owner_approval_is_required_and_transitions_asset():
    governance = Governance(Policy())
    approval = governance.approve(asset(), "LEO", "hatem")
    assert approval.decision == "approved"
    assert approval.tier.value == "external_communication"


def test_non_owner_cannot_approve_external_communication():
    governance = Governance(Policy())
    with pytest.raises(GovernanceViolation, match="only the human owner"):
        governance.approve(asset(), "LEO", "ANDY")


def test_self_approval_is_denied():
    governance = Governance(Policy())
    with pytest.raises(GovernanceViolation, match="self-approval"):
        governance.approve(asset(), "LEO", "LEO")


def test_publish_requires_approval_id_and_approved_status():
    governance = Governance(Policy())
    with pytest.raises(GovernanceViolation, match="owner-approved"):
        governance.assert_publishable(asset(AssetStatus.AWAITING_OWNER), "youtube", 0)


def test_publish_cap_blocks_queue():
    governance = Governance(Policy(max_weekly_publishes=1))
    ready = asset(AssetStatus.APPROVED)
    ready.approval_id = "approval-1"
    with pytest.raises(GovernanceViolation, match="weekly publish cap"):
        governance.assert_publishable(ready, "youtube", 1)


def test_forbidden_engagement_actions_fail_closed():
    governance = Governance(Policy())
    with pytest.raises(GovernanceViolation, match="engagement action"):
        governance.assert_action_allowed("follow")


def test_cloud_budget_zero_blocks_any_spend():
    governance = Governance(Policy(monthly_cloud_cents=0))
    with pytest.raises(GovernanceViolation, match="cloud budget blocked"):
        governance.assert_cloud_budget(0, 1)
