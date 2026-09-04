from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .content_quality_scorer import ContentQualityScorer
from .governance import Governance
from .models import AssetStatus, ContentRequest, MusicAsset, PodcastAsset, now_iso
from .toolchain import Toolchain, measure_silence_ratio, probe_media


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
        self._scorer = ContentQualityScorer(
            ffmpeg_bin=getattr(settings, "ffmpeg_bin", "ffmpeg"),
            ffprobe_bin="ffprobe",
        )

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
        # Real content analysis if video file exists
        if request.video_path:
            path = Path(request.video_path)
            if path.exists():
                expected = self._expected_duration(request, "video")
                report = self._scorer.analyze_video(path, expected_duration=int(expected))
                issues.extend(report.issues)
                score = min(score, report.score)
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
        # Real content analysis
        if asset.audio_path:
            path = Path(asset.audio_path)
            if path.exists():
                report = self._scorer.analyze_music(path, expected_duration=asset.duration_seconds)
                issues.extend(report.issues)
                score = min(score, report.score)
        passed = score >= self._settings.quality_gate_threshold
        auto_approved = False
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
        # Real content analysis
        if asset.audio_path:
            path = Path(asset.audio_path)
            if path.exists():
                report = self._scorer.analyze_podcast(path, expected_duration=asset.duration_target_seconds)
                issues.extend(report.issues)
                score = min(score, report.score)
        passed = score >= self._settings.quality_gate_threshold
        auto_approved = False
        return QualityCheckResult(
            passed=passed,
            score=max(0.0, score),
            issues=issues,
            checked_at=now_iso(),
            auto_approved=auto_approved,
        )

    def check_media_asset(self, asset: Any, media_path: str | None, content_type: str = "") -> QualityCheckResult:
        """Check the actual persisted preview before it can reach the owner gate."""
        issues: list[str] = []
        score = 1.0
        if not media_path:
            issues.append("missing generated preview")
            score -= 0.7
        else:
            path = Path(media_path)
            if not path.is_file():
                issues.append("generated preview file does not exist")
                score -= 0.7
            else:
                try:
                    if path.stat().st_size == 0:
                        issues.append("generated preview is empty")
                        score -= 0.7
                except OSError:
                    issues.append("generated preview cannot be read")
                    score -= 0.7

                toolchain = Toolchain.from_settings(self._settings)
                try:
                    media_info = probe_media(toolchain, path)
                    if not media_info:
                        issues.append("cannot probe media file")
                        score -= 0.5
                    else:
                        is_video = media_info.get("width", 0) > 0 and media_info.get("height", 0) > 0
                        if content_type in ("music", "podcast") and is_video:
                            issues.append("expected audio-only media but found a video stream")
                            score -= 0.5
                        if content_type == "video" and not is_video:
                            issues.append("expected video media but no video stream was found")
                            score -= 0.5
                        if is_video:
                            duration = media_info.get("duration", 0.0)
                            width = media_info.get("width", 0)
                            height = media_info.get("height", 0)
                            video_codec = media_info.get("video_codec", "")
                            audio_codec = media_info.get("audio_codec", "")
                            frame_rate = media_info.get("video_frame_rate", 0.0)
                            video_bit_rate = media_info.get("video_bit_rate", 0)

                            if duration <= 0:
                                issues.append("video duration is zero")
                                score -= 0.3
                            manifest = getattr(asset, "media_manifest", None) or {}
                            if manifest.get("resolution") == "short":
                                # Vertical Shorts: 720x1280 delivery.
                                if width < 700 or height < 1200:
                                    issues.append("shorts resolution below 720x1280")
                                    score -= 0.3
                            elif width < 1280 or height < 720:
                                issues.append("video resolution below 720p")
                                score -= 0.3
                            if frame_rate and frame_rate < 23:
                                issues.append("video frame rate below 23fps")
                                score -= 0.1
                            if video_bit_rate and video_bit_rate < 250_000:
                                issues.append("video bitrate is unusually low")
                                score -= 0.1
                            if video_codec not in ("h264", "vp9", "hevc"):
                                issues.append(f"unsupported video codec: {video_codec}")
                                score -= 0.3
                            if not audio_codec:
                                issues.append("video missing audio track")
                                score -= 0.2
                        else:
                            duration = media_info.get("duration", 0.0)
                            sample_rate = media_info.get("sample_rate", 0)
                            channels = media_info.get("channels", 0)

                            if duration <= 0:
                                issues.append("audio duration is zero")
                                score -= 0.3
                            if not sample_rate:
                                issues.append("audio sample rate is missing")
                                score -= 0.2
                            elif sample_rate != 48000:
                                issues.append("audio sample rate not 48kHz")
                                score -= 0.2
                            if not channels:
                                issues.append("audio channel count is missing")
                                score -= 0.2
                            elif channels != 2:
                                issues.append("audio channel count not stereo")
                                score -= 0.2

                            silence_ratio = measure_silence_ratio(toolchain, path, duration)
                            silence_threshold = 0.7 if content_type == "podcast" else 0.4
                            if silence_ratio >= silence_threshold:
                                issues.append("audio too silent")
                                score -= 0.3

                        # The owner asks for a specific runtime. Delivering a
                        # different one is a defect even when the file is valid,
                        # so check it rather than silently shipping the wrong length.
                        expected = self._expected_duration(asset, content_type)
                        if expected > 0 and duration > 0:
                            tolerance = max(1.5, expected * 0.05)
                            if abs(duration - expected) > tolerance:
                                issues.append(
                                    f"duration {duration:.1f}s does not match requested {expected:.0f}s"
                                )
                                score -= 0.3
                except Exception as exc:
                    issues.append(f"error checking media: {exc}")
                    score -= 0.5

        if getattr(asset, "status", None) is not AssetStatus.AWAITING_OWNER:
            issues.append("asset is not ready for owner review")
            score -= 0.2
        return QualityCheckResult(
            passed=score >= self._settings.quality_gate_threshold and not issues,
            score=max(0.0, score),
            issues=issues,
            checked_at=now_iso(),
            auto_approved=False,
        )

    @staticmethod
    def _expected_duration(asset: Any, content_type: str) -> float:
        """The runtime the owner actually asked for, per media type."""
        try:
            if content_type == "music":
                return float(getattr(asset, "duration_seconds", 0) or 0)
            if content_type == "podcast":
                return float(getattr(asset, "duration_target_seconds", 0) or 0)
            if content_type == "video":
                manifest = getattr(asset, "media_manifest", None) or {}
                return float(manifest.get("duration", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return 0.0

    def approve_content(self, request: ContentRequest, result: QualityCheckResult) -> ContentRequest:
        if result.auto_approved:
            request.stage = "ready_to_publish"
        elif result.passed:
            request.stage = "ready_to_publish"
        else:
            request.reject_quality(f"quality check failed: {', '.join(result.issues)}")
        request.updated_at = now_iso()
        return request
