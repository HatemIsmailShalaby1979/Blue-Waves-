from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings
from .governance import Governance
from .models import ContentRequest, MusicAsset, PodcastAsset, now_iso


@dataclass
class QualityCheckResult:
    passed: bool
    score: float
    issues: list[str]
    checked_at: str = ""
    auto_approved: bool = False


class QualityGates:
    """Multi-format quality assessment with auto-approve/reject."""

    def __init__(self, settings: Settings, governance: Governance) -> None:
        self._settings = settings
        self._governance = governance

    def check_video(self, request: ContentRequest) -> QualityCheckResult:
        issues = []
        score = 1.0
        if not request.video_path:
            issues.append("missing video file")
            score -= 0.5
        if not request.script:
            issues.append("missing script")
            score -= 0.3
        if request.error:
            issues.append(f"has error: {request.error}")
            score -= 0.4
        passed = score >= self._settings.quality_gate_threshold
        auto_approved = passed and request.estimated_cost_cents <= self._settings.auto_approve_under_cents
        return QualityCheckResult(
            passed=passed,
            score=max(0.0, score),
            issues=issues,
            checked_at=now_iso(),
            auto_approved=auto_approved,
        )

    def check_music(self, asset: MusicAsset) -> QualityCheckResult:
        issues = []
        score = 1.0
        if not asset.audio_path:
            issues.append("missing audio file")
            score -= 0.5
        if not asset.prompt:
            issues.append("missing prompt")
            score -= 0.2
        if asset.duration_seconds <= 0:
            issues.append("invalid duration")
            score -= 0.3
        passed = score >= self._settings.quality_gate_threshold
        auto_approved = passed and asset.provider in ("ace_step", "edge_tts")
        return QualityCheckResult(
            passed=passed,
            score=max(0.0, score),
            issues=issues,
            checked_at=now_iso(),
            auto_approved=auto_approved,
        )

    def check_podcast(self, asset: PodcastAsset) -> QualityCheckResult:
        issues = []
        score = 1.0
        if not asset.audio_path:
            issues.append("missing audio file")
            score -= 0.5
        if not asset.script:
            issues.append("missing script")
            score -= 0.3
        if asset.duration_target_seconds <= 0:
            issues.append("invalid duration")
            score -= 0.3
        passed = score >= self._settings.quality_gate_threshold
        auto_approved = passed and asset.tts_provider in ("edge_tts", "kokoro")
        return QualityCheckResult(
            passed=passed,
            score=max(0.0, score),
            issues=issues,
            checked_at=now_iso(),
            auto_approved=auto_approved,
        )

    def approve_content(self, request: ContentRequest, result: QualityCheckResult) -> ContentRequest:
        if result.auto_approved:
            request.stage = "ready_to_publish"
        elif result.passed:
            request.stage = "ready_to_publish"
        else:
            request.reject_quality(f"quality check failed: {', '.join(result.issues)}")
        request.updated_at = now_iso()
        return request
