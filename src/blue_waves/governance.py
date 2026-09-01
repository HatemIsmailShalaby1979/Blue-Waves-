from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .models import ApprovalRequest, ApprovalTier, AssetStatus, ContentAsset, CostEvent, now_iso


class GovernanceViolation(Exception):
    """A fail-closed policy decision."""


@dataclass(frozen=True)
class Policy:
    tenant_id: str = "bluewaves"
    owner_actor: str = "hatem"
    max_weekly_publishes: int = 5
    monthly_cloud_cents: int = 0
    allowed_channels: tuple[str, ...] = ("youtube", "tiktok", "linkedin", "x")
    forbidden_actions: tuple[str, ...] = ("like", "follow", "subscribe", "comment", "engagement_boost")
    max_weekly_music: int = 20
    max_weekly_podcasts: int = 5
    max_weekly_videos: int = 10
    max_podcast_duration_minutes: int = 60
    max_music_duration_seconds: int = 600
    auto_approve_under_cents: int = 0
    quality_gate_threshold: float = 0.7
    provider_fallback_enabled: bool = True


class Governance:
    """Blue Waves policy boundary.

    Codex owns the platform governance. Blue Waves owns these client-side constraints
    and sends the resulting evidence through its external Codex client.
    """

    def __init__(self, policy: Policy):
        self.policy = policy

    def assert_tenant(self, tenant_id: str) -> None:
        if tenant_id != self.policy.tenant_id:
            raise GovernanceViolation(f"tenant mismatch: expected {self.policy.tenant_id}, got {tenant_id}")

    def assert_publishable(self, asset: ContentAsset, channel: str, weekly_count: int) -> None:
        self.assert_tenant(asset.tenant_id)
        if channel not in self.policy.allowed_channels:
            raise GovernanceViolation(f"channel not allowed: {channel}")
        if asset.status is not AssetStatus.APPROVED:
            raise GovernanceViolation(f"asset must be owner-approved before publishing, got {asset.status}")
        if not asset.approval_id:
            raise GovernanceViolation("missing owner approval record")
        if weekly_count >= self.policy.max_weekly_publishes:
            raise GovernanceViolation("weekly publish cap reached; queue is blocked")

    def assert_action_allowed(self, action: str) -> None:
        if action.lower() in self.policy.forbidden_actions:
            raise GovernanceViolation(f"Blue Waves cannot perform engagement action: {action}")

    def approve(self, asset: ContentAsset, requested_by: str, approver: str, reason: str | None = None) -> ApprovalRequest:
        self.assert_tenant(asset.tenant_id)
        if requested_by == approver:
            raise GovernanceViolation("self-approval denied")
        if approver != self.policy.owner_actor:
            raise GovernanceViolation("only the human owner can approve external communication")
        if asset.status is not AssetStatus.AWAITING_OWNER:
            raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.APPROVED)
        approval_id = f"approval-{asset.asset_id}-{date.today().isoformat()}"
        asset.approval_id = approval_id
        return ApprovalRequest(
            approval_id=approval_id,
            asset_id=asset.asset_id,
            tenant_id=asset.tenant_id,
            requested_by=requested_by,
            tier=ApprovalTier.EXTERNAL_COMMUNICATION,
            decision="approved",
            decided_by=approver,
            decided_at=now_iso(),
            reason=reason,
        )

    def assert_cloud_budget(self, spent_cents: int, proposed_cents: int) -> None:
        if spent_cents + proposed_cents > self.policy.monthly_cloud_cents:
            raise GovernanceViolation(
                f"cloud budget blocked: {spent_cents + proposed_cents} cents would exceed "
                f"monthly ceiling of {self.policy.monthly_cloud_cents}"
            )

    def validate_claims(self, asset: ContentAsset) -> list[str]:
        return [claim.claim_id for claim in asset.claims if not claim.is_supported]

    def assert_autonomous_generation_allowed(self, content_type: str, weekly_count: int, estimated_cents: int) -> None:
        """Fail-closed: check all autonomous generation constraints."""
        if content_type == "video" and weekly_count >= self.policy.max_weekly_videos:
            raise GovernanceViolation(f"weekly video cap reached: {weekly_count}/{self.policy.max_weekly_videos}")
        if content_type == "music" and weekly_count >= self.policy.max_weekly_music:
            raise GovernanceViolation(f"weekly music cap reached: {weekly_count}/{self.policy.max_weekly_music}")
        if content_type == "podcast" and weekly_count >= self.policy.max_weekly_podcasts:
            raise GovernanceViolation(f"weekly podcast cap reached: {weekly_count}/{self.policy.max_weekly_podcasts}")
        self.assert_cloud_budget(0, estimated_cents)

    def assert_quality_gate(self, quality_score: float) -> bool:
        """Auto-approve if quality exceeds threshold, auto-reject if below."""
        return quality_score >= self.policy.quality_gate_threshold

    def assert_provider_fallback(self, failed_provider: str) -> str:
        """Select fallback provider when primary fails."""
        if not self.policy.provider_fallback_enabled:
            raise GovernanceViolation(f"provider {failed_provider} failed and fallback is disabled")
        fallbacks = {
            "kling": "seedance",
            "seedance": "hailuo",
            "suno_api": "ace_step",
            "kokoro": "edge_tts",
            "google_tts": "edge_tts",
        }
        return fallbacks.get(failed_provider, "ken_burns")

    def assert_publishable_music(self, asset: object, weekly_count: int) -> None:
        """Fail-closed: music must be owner-approved and within weekly cap."""
        self.assert_tenant(asset.tenant_id)
        if asset.status is not AssetStatus.APPROVED:
            raise GovernanceViolation(f"music asset not approved: {asset.status}")
        if not asset.approval_id:
            raise GovernanceViolation("music asset missing owner approval record")
        if weekly_count >= self.policy.max_weekly_music:
            raise GovernanceViolation("weekly music cap reached")

    def assert_publishable_podcast(self, asset: object, weekly_count: int) -> None:
        """Fail-closed: podcast must be owner-approved, within cap, and within duration limit."""
        self.assert_tenant(asset.tenant_id)
        if asset.status is not AssetStatus.APPROVED:
            raise GovernanceViolation(f"podcast asset not approved: {asset.status}")
        if not asset.approval_id:
            raise GovernanceViolation("podcast asset missing owner approval record")
        if weekly_count >= self.policy.max_weekly_podcasts:
            raise GovernanceViolation("weekly podcast cap reached")
        if hasattr(asset, "duration_target_seconds"):
            max_seconds = self.policy.max_podcast_duration_minutes * 60
            if asset.duration_target_seconds > max_seconds:
                raise GovernanceViolation(f"podcast exceeds max duration: {asset.duration_target_seconds}s")

    def assert_generation_allowed(self, content_type: str, provider: str, estimated_cents: int) -> None:
        """Fail-closed: block generation if budget would be exceeded."""
        if estimated_cents > self.policy.auto_approve_under_cents:
            self.assert_cloud_budget(0, estimated_cents)
