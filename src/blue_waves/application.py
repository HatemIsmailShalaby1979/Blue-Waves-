from __future__ import annotations

import json
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .codex_client import CodexClient, HttpCodexClient, InMemoryCodexClient
from .config import Settings
from .connections import ConnectionStore
from .engines import FactCheckEngine, ProductionEngine, ResearchEngine, ScriptEngine
from .finance import FinanceEngine
from .governance import Governance, GovernanceViolation, Policy
from .hybrid import HybridRouter, Stage
from .ingest import probe_video_file, resolution_label, sha256_file
from .jobs import JobManager, VideoJob
from .ledger import AppendOnlyLedger, JsonStore
from .models import (AssetStatus, ContentAsset, ContentRequest, CostEvent, Language, MetricEvent,
                     MusicAsset, PodcastAsset, asset_from_dict, music_asset_from_dict,
                     podcast_asset_from_dict, now_iso)
from .music_engine import MusicEngine
from .podcast_engine import PodcastEngine
from .enhancement import EnhancementError, MediaEnhancer
from .providers import DeferredMotionProvider, ProviderHealthMonitor, ProviderRegistry, configured_providers
from .provider_approvals import ProviderApprovalStore
from .monetization import MediaKitGenerator, SponsorTracker
from .quality_gates import QualityGates
from .queue import ContentQueue
from .scheduler import Scheduler
from .video_engine import VideoEngine
from .intelligence import MetacognitiveEngine, PerformanceMemory
from .youtube_upload import YouTubeUploadService, create_youtube_service_from_oauth


class BlueWavesApplication:
    """Business workflow for Blue Waves, independent of Codex implementation details."""

    # pylint: disable=too-many-instance-attributes  # facade aggregating every subsystem
    def __init__(self, settings: Settings | None = None, codex: CodexClient | None = None):
        self.settings = settings or Settings.from_env()
        self.settings.ensure_data_dir()
        self.connections = ConnectionStore(self.settings.data_dir)
        saved = {
            provider: self.connections.get(provider)
            for provider in ("openrouter", "groq", "nvidia_nim", "cerebras", "huggingface", "suno",
                             "kling", "seedance", "kokoro", "aimlapi", "kai", "elevenlabs",
                             "pexels", "pixabay")
        }
        overrides = {
            "openrouter_api_key": saved.get("openrouter", {}).get("api_key"),
            "groq_api_key": saved.get("groq", {}).get("api_key"),
            "nvidia_nim_api_key": saved.get("nvidia_nim", {}).get("api_key"),
            "cerebras_api_key": saved.get("cerebras", {}).get("api_key"),
            "huggingface_api_key": saved.get("huggingface", {}).get("api_key"),
            "suno_api_key": saved.get("suno", {}).get("api_key"),
            "kling_api_key": saved.get("kling", {}).get("api_key"),
            "seedance_api_key": saved.get("seedance", {}).get("api_key"),
            "kokoro_api_key": saved.get("kokoro", {}).get("api_key"),
            "aimlapi_api_key": saved.get("aimlapi", {}).get("api_key"),
            "elevenlabs_api_key": saved.get("elevenlabs", {}).get("api_key"),
            "kai_api_key": saved.get("kai", {}).get("api_key"),
            "pexels_api_key": saved.get("pexels", {}).get("api_key"),
            "pixabay_api_key": saved.get("pixabay", {}).get("api_key"),
        }
        self.settings = replace(self.settings, **{key: value for key, value in overrides.items() if value})
        self.policy = Policy(
            tenant_id=self.settings.tenant_id,
            owner_actor=self.settings.owner_actor,
            max_weekly_publishes=self.settings.max_weekly_publishes,
            monthly_cloud_cents=self.settings.monthly_cloud_cents,
            max_weekly_music=self.settings.max_weekly_music,
            max_weekly_podcasts=self.settings.max_weekly_podcasts,
            max_weekly_videos=self.settings.max_weekly_videos,
            max_podcast_duration_minutes=self.settings.max_podcast_duration_minutes,
            max_music_duration_seconds=self.settings.max_music_duration_seconds,
            auto_approve_under_cents=self.settings.auto_approve_under_cents,
            quality_gate_threshold=self.settings.quality_gate_threshold,
            provider_fallback_enabled=self.settings.provider_fallback_enabled,
        )
        self.governance = Governance(self.policy)
        self.store = JsonStore(self.settings.data_dir)
        self.ledger = AppendOnlyLedger(self.settings.data_dir / "audit.jsonl")
        self.provider_approvals = ProviderApprovalStore(self.settings.data_dir)
        self.sponsors = SponsorTracker(self.settings.data_dir)
        providers = configured_providers(self.settings)
        self.local_provider = providers["local"]
        cloud_providers = [
            providers[name]
            for name in ("openrouter", "groq", "cerebras", "nvidia_nim", "huggingface")
            if providers[name].configured
        ]
        cloud_provider = cloud_providers[0] if cloud_providers else None
        self.hybrid = HybridRouter(self.governance, self.local_provider, cloud_provider, clouds=cloud_providers)
        self.research = ResearchEngine()
        self.scripts = ScriptEngine(self.local_provider, cloud_provider, self.governance, cloud_providers=cloud_providers)
        self.fact_checker = FactCheckEngine(self.governance)
        self.production = ProductionEngine(self.governance, {
            "ffmpeg": self.settings.ffmpeg_bin,
            "voice": self.settings.piper_bin,
            "music": self.settings.ace_step_bin or "ACE-Step/local",
        })
        self.motion = DeferredMotionProvider()
        self.assets: dict[str, ContentAsset] = {}
        self.codex = codex or (
            HttpCodexClient(self.settings.codex_base_url, self.settings.tenant_id, self.settings.codex_api_key)
            if self.settings.codex_base_url else InMemoryCodexClient(self.settings.tenant_id)
        )
        self.health_monitor = ProviderHealthMonitor()
        self.provider_registry = ProviderRegistry(
            self.settings,
            approval_store=self.provider_approvals,
            health_monitor=self.health_monitor,
        )
        self.finance = FinanceEngine()
        self.music_engine = MusicEngine(self.settings, self.governance, self.provider_registry, self.health_monitor)
        self.podcast_engine = PodcastEngine(self.settings, self.governance, self.provider_registry, self.health_monitor)
        self.video_engine = VideoEngine(self.settings, self.governance, self.provider_registry, self.health_monitor)
        self.queue = ContentQueue(self.settings)
        self.jobs = JobManager(max_workers=1)
        self.scheduler = Scheduler(
            self.settings, self.governance, self.queue,
            executor=self._execute_scheduled_job,
        )
        self.quality_gates = QualityGates(self.settings, self.governance)
        self.enhancer = MediaEnhancer(enabled=self.settings.enhancement_enabled)
        self.enhancement_profile = self.settings.enhancement_profile
        self.metacognition = MetacognitiveEngine()
        self.music_assets: dict[str, MusicAsset] = {}
        self.podcast_assets: dict[str, PodcastAsset] = {}
        self._youtube_service: YouTubeUploadService | None = None
        self._init_youtube_service()
        self._load_persisted_assets()
        for event in self.store.latest_metrics():
            self.metacognition.restore_metric(event)

    def _execute_scheduled_job(self, job: Any) -> dict[str, Any] | None:
        """Generate content for a scheduled job with quality-gate verification.

        Routes to the correct engine, runs generation, then runs the quality
        gate on the output. On success the asset is already in
        ``awaiting_owner`` (set by the engine). On quality failure an error
        dict is returned so the scheduler retries with an enhancement note.
        """
        request = next((r for r in self.queue.get_all() if r.id == job.request_id), None)
        if not request:
            return {"error": f"request not found: {job.request_id}"}
        content_type = job.content_type
        # Pick up the enhancement note from a previous failed attempt, if any.
        enhancement = ""
        try:
            prev = getattr(job, "result", None) or {}
            enhancement = str(prev.get("enhancement", "") or "")
        except Exception:
            enhancement = ""
        topic = request.topic + (f" — enhancement: {enhancement}" if enhancement else "")
        quality = getattr(request, "quality", "high") or "high"
        try:
            if content_type == "music":
                asset = self.generate_music(topic=topic, quality=quality, duration_seconds=60)
                if not asset:
                    return {"error": f"{content_type} generation failed"}
                check = self.quality_gates.check_media_asset(asset, asset.audio_path, "music")
            elif content_type == "podcast":
                asset = self.generate_podcast(
                    topic=topic, script=request.script or topic, quality=quality,
                    language=getattr(request, "language", "en") or "en",
                    duration_seconds=60,
                )
                if not asset:
                    return {"error": f"{content_type} generation failed"}
                check = self.quality_gates.check_media_asset(asset, asset.audio_path, "podcast")
            elif content_type == "video":
                asset = self.generate_video(topic=topic, prompt=topic, quality=quality, duration=5)
                if not asset:
                    return {"error": f"{content_type} generation failed"}
                check = self.quality_gates.check_media_asset(
                    asset, asset.media_manifest.get("video_path"), "video")
            else:
                return {"error": f"unsupported content type: {content_type}"}
        except Exception as exc:
            return {"error": f"{content_type} generation exception: {exc}"}
        asset.quality_score, asset.quality_issues = check.score, check.issues
        if not check.passed:
            return {"error": f"quality gate failed (score {check.score:.2f}): {'; '.join(check.issues[:3])}"}
        return {"asset_id": getattr(asset, "asset_id", None), "quality_score": check.score}

    def _load_persisted_assets(self) -> None:
        for raw in self.store.latest_assets():
            asset = asset_from_dict(raw)
            self.assets[asset.asset_id] = asset
        for raw in self.store.latest_music():
            asset = music_asset_from_dict(raw)
            self.music_assets[asset.asset_id] = asset
        for raw in self.store.latest_podcasts():
            asset = podcast_asset_from_dict(raw)
            self.podcast_assets[asset.asset_id] = asset

    def _init_youtube_service(self) -> None:
        """Initialize YouTube upload service from saved OAuth credentials."""
        if not self.settings.youtube_upload_enabled:
            return
        youtube_conn = self.connections.get("youtube")
        if not youtube_conn.get("access_token"):
            return
        try:
            self._youtube_service = create_youtube_service_from_oauth(youtube_conn, self.settings.data_dir)
        except Exception as exc:
            # Log but don't fail initialization - upload will fail at publish time with clear error
            self.ledger.append("youtube_init_failed", {"error": str(exc)}, self.settings.tenant_id, "LEO")

    def _get_youtube_service(self) -> YouTubeUploadService:
        """Get YouTube service, raising if not configured."""
        if self._youtube_service is None:
            self._init_youtube_service()
        if self._youtube_service is None:
            raise RuntimeError(
                "YouTube upload not configured. "
                "Enable YOUTUBE_UPLOAD_ENABLED and complete OAuth flow in Cockpit."
            )
        return self._youtube_service

    def register(self) -> dict[str, Any]:
        response = self.codex.register_blue_waves()
        self.ledger.append("blue_waves_registered", response, self.settings.tenant_id, "TOMY")
        return response

    def create_bilingual_lesson(
        self,
        topic: str,
        source_url: str | None = None,
        source_verified: bool = False,
        lesson_id: str | None = None,
    ) -> tuple[ContentAsset, ContentAsset]:
        result = self.research.propose(topic, source_url, source_verified=source_verified)
        self.ledger.append("research_completed", {
            "topic": result.topic,
            "angle": result.angle,
            "source_count": len(result.sources),
        }, self.settings.tenant_id, "MIRA")
        ar, en = self.scripts.create_assets(result, lesson_id)
        for asset in (ar, en):
            self.assets[asset.asset_id] = asset
            self.store.save_asset(asset)
            self.ledger.append(
                "script_created",
                {"asset_id": asset.asset_id, "language": asset.language.value},
                asset.tenant_id,
                "ZACK",
            )
        return ar, en

    def get_asset(self, asset_id: str) -> ContentAsset:
        try:
            return self.assets[asset_id]
        except KeyError as exc:
            raise KeyError(f"unknown asset: {asset_id}") from exc

    def fact_check_and_produce(self, asset: ContentAsset) -> dict[str, Any]:
        unsupported = self.fact_checker.review(asset)
        if unsupported:
            self.store.save_asset(asset)
            self.ledger.append(
                "fact_check_blocked",
                {"asset_id": asset.asset_id, "claim_ids": unsupported},
                asset.tenant_id,
                "ANDY",
            )
            return {"asset_id": asset.asset_id, "ready": False, "unsupported_claims": unsupported}
        motion_route = self.hybrid.route(Stage.MOTION)
        self.hybrid.assert_route_is_allowed(motion_route)
        manifest = self.production.plan(asset)
        manifest["motion_route"] = {
            "mode": motion_route.mode,
            "provider": motion_route.provider,
            "reason": motion_route.reason,
        }
        self.store.save_asset(asset)
        self.ledger.append(
            "production_manifest_created",
            {"asset_id": asset.asset_id, "manifest": manifest},
            asset.tenant_id,
            "BELAL",
        )
        return {"asset_id": asset.asset_id, "ready": True, "manifest": manifest}

    def owner_approve(
        self,
        asset: ContentAsset,
        reason: str = "owner reviewed preview",
        approver: str | None = None,
    ) -> dict[str, Any]:
        # Legacy lesson approval predates rendered media; generated v0.2 videos
        # carry a concrete preview path and must pass the preview guard.
        quality_score: float | None = None
        if "video_path" in asset.media_manifest:
            preview_path = asset.media_manifest.get("video_path")
            self._assert_preview_exists(preview_path)
            quality = self.quality_gates.check_media_asset(asset, preview_path, "video")
            asset.quality_score, asset.quality_issues = quality.score, quality.issues
            quality_score = quality.score
            if not quality.passed:
                raise GovernanceViolation(f"owner approval blocked by quality gate: {', '.join(quality.issues)}")
        approval = self.governance.approve(
            asset,
            requested_by="LEO",
            approver=approver or self.settings.owner_actor,
            reason=reason,
        )
        self.store.save_asset(asset)
        payload = asdict(approval)
        payload["tier"] = approval.tier.value
        payload["status"] = "approved"
        payload["quality_score"] = quality_score
        self.ledger.append("owner_approved_external_communication", payload, asset.tenant_id, self.settings.owner_actor)
        return payload

    def publish(self, asset: ContentAsset, channel: str, weekly_count: int = 0) -> dict[str, Any]:
        self.governance.assert_publishable(asset, channel, weekly_count)
        self.governance.assert_action_allowed("publish")

        # Actually upload to YouTube if channel is youtube and upload is enabled
        youtube_result = None
        if channel == "youtube" and self.settings.youtube_upload_enabled:
            youtube_service = self._get_youtube_service()
            video_path = Path(asset.media_manifest.get("video_path", ""))
            if video_path.exists():
                # Generate SEO metadata
                seo = youtube_service.generate_seo_metadata(
                    content_type="video",
                    topic=asset.topic,
                    pillar=asset.pillar,
                    language=asset.language.value,
                )
                youtube_result = youtube_service.upload_video(
                    video_path=video_path,
                    title=seo["title"],
                    description=seo["description"],
                    tags=seo["tags"],
                    category_id=seo["category_id"],
                    privacy_status="private",  # Start private, owner can change
                )
                asset.media_manifest["youtube_video_id"] = youtube_result["video_id"]
                asset.media_manifest["youtube_url"] = youtube_result["video_url"]
                asset.media_manifest["seo_metadata"] = seo

        asset.transition(AssetStatus.PUBLISHED)
        publication = {
            "publication_id": f"pub-{uuid.uuid4().hex[:10]}",
            "asset_id": asset.asset_id,
            "tenant_id": asset.tenant_id,
            "channel": channel,
            "language": asset.language.value,
            "published_at": now_iso(),
            "approval_id": asset.approval_id,
            "youtube": youtube_result,
        }
        self.store.save_asset(asset)
        self.ledger.append("published", publication, asset.tenant_id, "LEO")
        self.codex.emit_event("content_published", publication)
        return publication

    def record_metric(
        self,
        asset: ContentAsset,
        channel: str,
        metric: str,
        value: float,
        source: str = "owner_import",
    ) -> dict[str, Any]:
        event = MetricEvent(
            event_id=f"metric-{uuid.uuid4().hex[:10]}",
            tenant_id=asset.tenant_id,
            asset_id=asset.asset_id,
            channel=channel,
            metric=metric,
            value=value,
            source=source,
        )
        self.store.save_metric(event)
        payload = asdict(event)
        self.ledger.append("metric_recorded", payload, asset.tenant_id, "JOE")
        self.codex.emit_event("audience_metric_recorded", payload)
        self.metacognition.add_metric(payload)
        return payload

    def record_media_metric(
        self,
        asset_id: str,
        channel: str,
        metric: str,
        value: float,
        source: str = "owner_import",
    ) -> dict[str, Any]:
        if asset_id in self.music_assets:
            asset = self.music_assets[asset_id]
            topic, tenant = asset.title, asset.tenant_id
        elif asset_id in self.podcast_assets:
            asset = self.podcast_assets[asset_id]
            topic, tenant = asset.topic, asset.tenant_id
        else:
            raise KeyError(f"unknown media asset: {asset_id}")
        event = MetricEvent(
            event_id=f"metric-{uuid.uuid4().hex[:10]}",
            tenant_id=tenant,
            asset_id=asset_id,
            channel=channel,
            metric=metric,
            value=value,
            source=source,
        )
        payload = asdict(event)
        self.store.save_metric(event)
        self.metacognition.add_metric(payload)
        self.ledger.append("metric_recorded", {**payload, "topic": topic}, tenant, "JOE")
        return payload

    def fetch_youtube_analytics(self, video_id: str) -> dict[str, Any]:
        """Fetch analytics from YouTube Data API for a published video."""
        if not self.settings.youtube_upload_enabled:
            raise RuntimeError("YouTube upload not enabled")
        youtube_service = self._get_youtube_service()
        return youtube_service.get_video_analytics(video_id)

    def sync_published_metrics(self, asset_id: str) -> dict[str, Any]:
        """Fetch and record YouTube analytics for a published asset."""
        if asset_id in self.assets:
            asset = self.assets[asset_id]
        elif asset_id in self.music_assets:
            asset = self.music_assets[asset_id]
        elif asset_id in self.podcast_assets:
            asset = self.podcast_assets[asset_id]
        else:
            raise KeyError(f"unknown asset: {asset_id}")

        youtube_id = asset.media_manifest.get("youtube_video_id")
        if not youtube_id:
            raise ValueError(f"Asset {asset_id} has no YouTube video ID")

        analytics = self.fetch_youtube_analytics(youtube_id)
        for metric_name, value in analytics.items():
            self.record_media_metric(asset_id, "youtube", metric_name, float(value), source="youtube_api")

        return analytics

    def sync_all_published_metrics(self) -> dict[str, Any]:
        """Fetch and record YouTube analytics for every published asset that has a video ID."""
        published = [
            asset
            for asset in (
                list(self.assets.values())
                + list(self.music_assets.values())
                + list(self.podcast_assets.values())
            )
            if asset.status == AssetStatus.PUBLISHED and asset.media_manifest.get("youtube_video_id")
        ]
        results: dict[str, Any] = {"synced": [], "failed": []}
        for asset in published:
            try:
                analytics = self.sync_published_metrics(asset.asset_id)
                results["synced"].append({"asset_id": asset.asset_id, "analytics": analytics})
            except Exception as exc:
                results["failed"].append({"asset_id": asset.asset_id, "error": str(exc)})
        return results

    def run_automated_cycle(self, max_items: int = 3, max_attempts: int = 3) -> dict[str, Any]:
        """Automated content pipeline (Phase 9).

        1. Check queue for pending requests.
        2. For each: generate content via the appropriate engine.
        3. Run the quality gate on the output.
        4. If passed: asset stays in ``awaiting_owner``; request → ``ready_to_publish``.
        5. If failed: retry with an enhancement note (up to ``max_attempts``).
        6. Log every step to the ledger.
        7. Return a cycle summary.
        """
        pending = [r for r in self.queue.get_all() if r.stage == "queued"]
        order = {"high": 0, "normal": 1, "low": 2}
        pending.sort(key=lambda r: order.get(getattr(r, "priority", "normal"), 1))
        batch = pending[:max_items]

        self.ledger.append("automated_cycle_started",
                           {"pending": len(pending), "batch": len(batch)},
                           self.settings.tenant_id, "LEO")

        details: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for request in batch:
            last_error: str | None = None
            asset_id: str | None = None
            quality_score: float | None = None
            attempts_used = 0
            for attempt in range(1, max_attempts + 1):
                attempts_used = attempt
                enhancement = "" if attempt == 1 else f"Improve quality and clarity (retry {attempt}/{max_attempts})."
                topic = request.topic if attempt == 1 else f"{request.topic} — enhancement: {enhancement}"
                self.ledger.append("automated_generation_attempt",
                                   {"request_id": request.id, "content_type": request.content_type,
                                    "topic": topic, "attempt": attempt},
                                   self.settings.tenant_id, "LEO")
                try:
                    if request.content_type == "music":
                        asset = self.generate_music(topic=topic, quality=request.quality or "high",
                                                    duration_seconds=60)
                        media_path = asset.audio_path if asset else None
                    elif request.content_type == "podcast":
                        asset = self.generate_podcast(
                            topic=topic, script=request.script or topic,
                            quality=request.quality or "high",
                            language=getattr(request, "language", "en") or "en",
                            duration_seconds=60)
                        media_path = asset.audio_path if asset else None
                    elif request.content_type == "video":
                        asset = self.generate_video(topic=topic, prompt=topic,
                                                    quality=request.quality or "high", duration=5)
                        media_path = asset.media_manifest.get("video_path") if asset else None
                    else:
                        last_error = f"unsupported content type: {request.content_type}"
                        asset = None
                        media_path = None
                except Exception as exc:
                    asset = None
                    media_path = None
                    last_error = f"generation exception: {exc}"

                if asset is None:
                    last_error = last_error or "generation returned no asset"
                    self.ledger.append("automated_generation_failed",
                                       {"request_id": request.id, "attempt": attempt, "error": last_error},
                                       self.settings.tenant_id, "LEO")
                    continue

                # Quality gate on the produced preview.
                try:
                    check = self.quality_gates.check_media_asset(asset, media_path, request.content_type)
                except Exception as exc:
                    last_error = f"quality check exception: {exc}"
                    self.ledger.append("automated_quality_failed",
                                       {"request_id": request.id, "asset_id": getattr(asset, "asset_id", None),
                                        "attempt": attempt, "error": last_error},
                                       self.settings.tenant_id, "LEO")
                    continue
                asset.quality_score, asset.quality_issues = check.score, check.issues
                quality_score = check.score
                asset_id = getattr(asset, "asset_id", None)
                if check.passed:
                    # Engines leave assets in awaiting_owner; mark the queue
                    # request ready for owner review.
                    try:
                        request.approve_quality()
                    except Exception:
                        request.stage = "ready_to_publish"
                    self.ledger.append("automated_quality_passed",
                                       {"request_id": request.id, "asset_id": asset_id,
                                        "quality_score": check.score, "attempt": attempt},
                                       self.settings.tenant_id, "LEO")
                    last_error = None
                    break
                last_error = f"quality gate failed (score {check.score:.2f}): {'; '.join(check.issues[:3])}"
                self.ledger.append("automated_quality_failed",
                                   {"request_id": request.id, "asset_id": asset_id,
                                    "attempt": attempt, "error": last_error},
                                   self.settings.tenant_id, "LEO")

            if last_error is None:
                succeeded += 1
                status = "awaiting_owner"
            else:
                failed += 1
                status = "failed"
                try:
                    request.set_error(f"automated cycle retries exhausted after {attempts_used} attempts: {last_error}")
                except Exception:
                    pass
                self.ledger.append("automated_request_failed",
                                   {"request_id": request.id, "attempts": attempts_used, "error": last_error},
                                   self.settings.tenant_id, "LEO")

            details.append({"request_id": request.id, "content_type": request.content_type,
                            "topic": request.topic, "status": status, "asset_id": asset_id,
                            "attempts": attempts_used, "quality_score": quality_score,
                            "error": last_error})

        summary = {"processed": len(batch), "succeeded": succeeded, "failed": failed, "details": details}
        self.ledger.append("automated_cycle_completed", summary, self.settings.tenant_id, "LEO")
        return summary

    def run_scheduler_tick(self) -> dict[str, Any]:
        """Run one scheduler cycle: automated pipeline + due jobs + analytics."""
        try:
            cycle = self.run_automated_cycle(max_items=self.settings.scheduler_max_concurrent)
        except Exception as exc:
            cycle = {"processed": 0, "succeeded": 0, "failed": 0,
                     "details": [], "error": str(exc)}
        try:
            tick = self.scheduler.tick(max_jobs=self.settings.scheduler_max_concurrent)
        except Exception as exc:
            tick = {"processed": 0, "succeeded": 0, "failed": 0, "details": [], "error": str(exc)}
        due = self.scheduler.execute_due_jobs(max_concurrent=self.settings.scheduler_max_concurrent)
        analytics: dict[str, Any] = {"synced": [], "failed": []}
        if self.settings.youtube_upload_enabled:
            try:
                analytics = self.sync_all_published_metrics()
            except Exception as exc:
                analytics = {"synced": [], "failed": [{"error": str(exc)}]}
        return {
            "automated_cycle": cycle,
            "scheduler_tick": tick,
            "executed": [{"job_id": job.job_id, "status": job.status, "result": job.result} for job in due],
            "analytics": analytics,
        }

    def generate_media_kit(self) -> dict[str, Any]:
        """Build a sponsor-facing media kit from recorded metrics and content counts."""
        assets = {
            "videos": len(self.assets),
            "music": len(self.music_assets),
            "podcasts": len(self.podcast_assets),
        }
        generator = MediaKitGenerator(metrics=self.store.latest_metrics(), assets=assets)
        return generator.generate(
            channel_name=self.settings.tenant_id,
            channel_url=self.settings.youtube_channel_id or "",
        )

    def outreach_email_for(self, prospect_id: str, company: str = "") -> str:
        prospect = self.sponsors.get(prospect_id)
        generator = MediaKitGenerator(
            metrics=self.store.latest_metrics(),
            assets={
                "videos": len(self.assets),
                "music": len(self.music_assets),
                "podcasts": len(self.podcast_assets),
            },
        )
        return generator.outreach_email(prospect, company)

    def sponsor_pipeline(self) -> dict[str, Any]:
        return {
            "prospects": self.sponsors.list_prospects(),
            "summary": self.sponsors.pipeline_summary(),
        }

    def generate_podcast_rss(self, base_url: str = "") -> str:
        """Generate RSS 2.0 feed for published podcasts.

        Supports both YouTube-hosted podcasts and local audio files.
        For local files, provides a placeholder URL that can be replaced when hosted.
        """
        import xml.etree.ElementTree as ET
        from datetime import datetime

        rss = ET.Element("rss", version="2.0", xmlns_itunes="http://www.itunes.com/dtds/podcast-1.0.dtd")
        channel = ET.SubElement(rss, "channel")

        ET.SubElement(channel, "title").text = "Blue Waves Podcasts"
        ET.SubElement(channel, "link").text = base_url or "https://bluewaves.example.com"
        ET.SubElement(channel, "description").text = "Educational podcasts from Blue Waves"
        ET.SubElement(channel, "language").text = "en"
        ET.SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

        # iTunes specific tags
        itunes_owner = ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}owner")
        ET.SubElement(itunes_owner, "{http://www.itunes.com/dtds/podcast-1.0.dtd}name").text = "Blue Waves"
        ET.SubElement(
            itunes_owner,
            "{http://www.itunes.com/dtds/podcast-1.0.dtd}email",
        ).text = "podcasts@bluewaves.example.com"
        ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}category", text="Education")
        ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit").text = "false"

        # Add podcast items
        for asset in sorted(self.podcast_assets.values(), key=lambda a: a.created_at, reverse=True):
            if asset.status != AssetStatus.PUBLISHED:
                continue

            # Determine audio URL - prefer YouTube, fallback to local path
            youtube_id = asset.media_manifest.get("youtube_video_id")
            if youtube_id:
                audio_url = f"https://www.youtube.com/watch?v={youtube_id}"
                audio_type = "audio/mpeg"
            elif asset.audio_path:
                # For local files, use a placeholder that should be replaced when hosted
                audio_url = f"{base_url.rstrip('/')}/audio/{asset.asset_id}.wav" if base_url else f"file://{asset.audio_path}"
                audio_type = "audio/wav"
            else:
                continue  # Skip if no audio source

            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = asset.title
            ET.SubElement(item, "description").text = f"Podcast about {asset.topic}"
            ET.SubElement(item, "pubDate").text = datetime.fromisoformat(
                asset.created_at.replace('Z', '+00:00')
            ).strftime("%a, %d %b %Y %H:%M:%S GMT")
            ET.SubElement(item, "guid").text = asset.asset_id

            # Enclosure for audio
            ET.SubElement(item, "enclosure", url=audio_url, type=audio_type, length="0")

            # iTunes tags
            ET.SubElement(
                item,
                "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration",
            ).text = str(asset.duration_target_seconds)
            ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType").text = "full"

        # Pretty print
        ET.indent(rss, space="  ")
        return ET.tostring(rss, encoding="unicode", xml_declaration=True)

    def reject_asset(self, asset: ContentAsset, reason: str = "owner rejected", approver: str | None = None) -> dict[str, Any]:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        # An unlisted upload can still be abandoned by the owner: the video stays
        # on YouTube but the asset never reaches ``published``.
        if asset.status not in (AssetStatus.AWAITING_OWNER, AssetStatus.UPLOADED_UNLISTED):
            raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED)
        asset.rejection_reason = reason
        self.store.save_asset(asset)
        self.ledger.append(
            "asset_rejected",
            {"asset_id": asset.asset_id, "reason": reason},
            asset.tenant_id,
            self.settings.owner_actor,
        )
        return {"asset_id": asset.asset_id, "status": "rejected", "reason": reason}

    def reject_music(self, asset_id: str, reason: str = "owner rejected", approver: str | None = None) -> dict[str, Any]:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        asset = self.music_assets.get(asset_id)
        if not asset:
            raise KeyError(f"unknown music asset: {asset_id}")
        if asset.status is not AssetStatus.AWAITING_OWNER:
            raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED)
        asset.rejection_reason = reason
        self.store.save_music(asset)
        self.ledger.append(
            "music_rejected",
            {"asset_id": asset_id, "reason": reason},
            self.settings.tenant_id,
            self.settings.owner_actor,
        )
        return {"asset_id": asset_id, "status": "rejected", "reason": reason}

    def reject_podcast(self, asset_id: str, reason: str = "owner rejected", approver: str | None = None) -> dict[str, Any]:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        asset = self.podcast_assets.get(asset_id)
        if not asset:
            raise KeyError(f"unknown podcast asset: {asset_id}")
        if asset.status is not AssetStatus.AWAITING_OWNER:
            raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED)
        asset.rejection_reason = reason
        self.store.save_podcast(asset)
        self.ledger.append(
            "podcast_rejected",
            {"asset_id": asset_id, "reason": reason},
            self.settings.tenant_id,
            self.settings.owner_actor,
        )
        return {"asset_id": asset_id, "status": "rejected", "reason": reason}

    def retry_music(self, asset_id: str, enhancement: str = "Improve arrangement, dynamics, and clarity.",
                    quality: str = "high", approver: str | None = None) -> MusicAsset:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        previous = self.music_assets.get(asset_id)
        if not previous or previous.status is not AssetStatus.REJECTED:
            raise GovernanceViolation("only a rejected music preview can be retried")
        asset = self.generate_music(
            topic=f"{previous.title.removeprefix('Music for ')} — enhancement: {enhancement}",
            genre=previous.genre, mood=previous.mood, duration_seconds=previous.duration_seconds, quality=quality,
        )
        if not asset:
            raise RuntimeError("retry generation failed")
        asset.attempt = previous.attempt + 1
        asset.parent_asset_id = previous.asset_id
        asset.metadata["enhancement"] = enhancement
        self.store.save_music(asset)
        self.ledger.append(
            "music_retry_generated",
            {
                "asset_id": asset.asset_id,
                "parent_asset_id": asset_id,
                "attempt": asset.attempt,
                "enhancement": enhancement,
            },
            self.settings.tenant_id,
            "BELAL",
        )
        return asset

    def retry_podcast(self, asset_id: str, enhancement: str = "Improve pacing, diction, and mix balance.",
                      quality: str = "high", approver: str | None = None) -> PodcastAsset:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        previous = self.podcast_assets.get(asset_id)
        if not previous or previous.status is not AssetStatus.REJECTED:
            raise GovernanceViolation("only a rejected podcast preview can be retried")
        asset = self.generate_podcast(
            topic=f"{previous.topic} — enhancement: {enhancement}", script=previous.script,
            host_voice=previous.host_voice, guest_voice=previous.guest_voice,
            host_name=previous.host_name, guest_name=previous.guest_name,
            duration_seconds=previous.duration_target_seconds, quality=quality,
        )
        if not asset:
            raise RuntimeError("retry generation failed")
        asset.attempt = previous.attempt + 1
        asset.parent_asset_id = previous.asset_id
        asset.metadata["enhancement"] = enhancement
        self.store.save_podcast(asset)
        self.ledger.append(
            "podcast_retry_generated",
            {
                "asset_id": asset.asset_id,
                "parent_asset_id": asset_id,
                "attempt": asset.attempt,
                "enhancement": enhancement,
            },
            self.settings.tenant_id,
            "ZACK",
        )
        return asset

    def retry_video(self, asset_id: str, enhancement: str = "Improve visual pacing, composition, and readability.",
                    quality: str = "high", approver: str | None = None) -> ContentAsset:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        previous = self.assets.get(asset_id)
        if not previous or previous.status is not AssetStatus.REJECTED:
            raise GovernanceViolation("only a rejected video preview can be retried")
        asset = self.generate_video(
            topic=previous.topic, prompt=f"{previous.topic}. {enhancement}",
            duration=int(previous.media_manifest.get("duration", 5)), quality=quality,
        )
        if not asset:
            raise RuntimeError("retry generation failed")
        asset.attempt = previous.attempt + 1
        asset.parent_asset_id = previous.asset_id
        asset.media_manifest["enhancement"] = enhancement
        self.store.save_asset(asset)
        self.ledger.append(
            "video_retry_generated",
            {
                "asset_id": asset.asset_id,
                "parent_asset_id": asset_id,
                "attempt": asset.attempt,
                "enhancement": enhancement,
            },
            self.settings.tenant_id,
            "BELAL",
        )
        return asset

    def intelligence(self) -> dict[str, Any]:
        assets: dict[str, dict[str, Any]] = {}
        for asset in self.assets.values():
            assets[asset.asset_id] = {
                "content_type": "video",
                "topic": asset.topic,
                "provider": asset.media_manifest.get("provider", "unknown"),
            }
        for asset in self.music_assets.values():
            assets[asset.asset_id] = {"content_type": "music", "topic": asset.title, "provider": asset.provider}
        for asset in self.podcast_assets.values():
            assets[asset.asset_id] = {"content_type": "podcast", "topic": asset.topic, "provider": asset.tts_provider}
        return {
            "performance_ranking": self.metacognition.rank_assets(assets),
            "shipo": self.metacognition.shipo_recommendations(assets),
            "approved_memory": self.metacognition.memories(),
        }

    def approve_memory(self, memory_id: str) -> dict[str, Any]:
        candidate = next(
            (
                item
                for item in self.metacognition.rank_assets(self._intelligence_assets())
                if item["memory_id"] == memory_id
            ),
            None,
        )
        if not candidate:
            raise KeyError(f"unknown memory proposal: {memory_id}")
        memory = PerformanceMemory(**candidate)
        approved = self.metacognition.approve(memory)
        self.store.save_memory(approved)
        self.ledger.append(
            "performance_memory_approved",
            approved.to_dict(),
            self.settings.tenant_id,
            self.settings.owner_actor,
        )
        return approved.to_dict()

    def _intelligence_assets(self) -> dict[str, dict[str, Any]]:
        data = {}
        for a in self.assets.values():
            data[a.asset_id] = {
                "content_type": "video",
                "topic": a.topic,
                "provider": a.media_manifest.get("provider", "unknown"),
            }
        for a in self.music_assets.values():
            data[a.asset_id] = {"content_type":"music", "topic":a.title, "provider":a.provider}
        for a in self.podcast_assets.values():
            data[a.asset_id] = {"content_type":"podcast", "topic":a.topic, "provider":a.tts_provider}
        return data

    def weekly_review(self) -> dict[str, Any]:
        assets = self.store.latest_assets()
        integrity, message = self.ledger.verify()
        proposal = {
            "proposal_id": f"proposal-{uuid.uuid4().hex[:10]}",
            "tenant_id": self.settings.tenant_id,
            "proposed_by": "KOYOSHU",
            "status": "proposed",
            "baseline": "no_change",
            "observations": {
                "assets": len(assets),
                "published": sum(1 for asset in assets if asset.get("status") == AssetStatus.PUBLISHED.value),
                "awaiting_owner": sum(1 for asset in assets if asset.get("status") == AssetStatus.AWAITING_OWNER.value),
                "ledger": message,
            },
            "recommendation": "Keep the current cadence until at least 3 bilingual lessons have comparable metrics.",
            "apply": False,
        }
        self.ledger.append("weekly_improvement_proposal", proposal, self.settings.tenant_id, "KOYOSHU")
        return {"ledger_intact": integrity, **proposal}

    def health(self) -> dict[str, Any]:
        integrity, message = self.ledger.verify()
        return {
            "service": "blue-waves",
            "version": "0.3.0",
            "tenant_id": self.settings.tenant_id,
            "codex_adapter": type(self.codex).__name__,
            "ledger_intact": integrity,
            "ledger_message": message,
            "cloud_budget_cents": self.settings.monthly_cloud_cents,
            "cloud_motion": (
                [
                    name for name in self.provider_registry.list_providers()["video"]
                    if name != "ken_burns"
                ]
                or "deferred_until_verified_provider"
            ),
            "configured_cloud_motion": [
                name for name in self.provider_registry.list_providers()["video"]
                if name != "ken_burns"
            ],
            "hybrid_motion_route": self.hybrid.route(Stage.MOTION).mode,
            "queue_size": self.queue.size(),
            "music_assets": len(self.music_assets),
            "podcast_assets": len(self.podcast_assets),
            "provider_rotation": self.provider_registry.rotation.snapshot(),
        }

    def add_content_request(self, content_type: str, topic: str, priority: str = "normal",
                            quality: str = "high", language: str = "en") -> ContentRequest:
        request = ContentRequest(
            id=f"req-{uuid.uuid4().hex[:10]}",
            content_type=content_type,
            topic=topic,
            priority=priority,
            quality=quality,
            language=language,
        )
        self.queue.add(request)
        self.ledger.append("content_request_added", request.to_dict(), self.settings.tenant_id, "MIRA")
        return request

    def generate_music(self, topic: str, genre: str = "cinematic", mood: str = "inspirational",
                       duration_seconds: int = 180, quality: str = "high") -> MusicAsset | None:
        estimated = self.provider_registry.estimated_cost_for("music", quality)
        self.governance.assert_autonomous_generation_allowed(
            "music", self.queue.get_weekly_count("music"), estimated
        )
        result = self.music_engine.generate(
            topic=topic, genre=genre, mood=mood,
            duration_seconds=duration_seconds, quality=quality,
        )
        if result.success and result.asset:
            self._enhance_music_asset(result.asset)
            self.music_assets[result.asset.asset_id] = result.asset
            self.store.save_music(result.asset)
            self._record_generation_cost("music", result.asset.asset_id, result.provider_used)
            self.ledger.append("music_generated", {
                "asset_id": result.asset.asset_id,
                "provider": result.provider_used,
            }, self.settings.tenant_id, "BELAL")
            return result.asset
        # Loud failure with the per-provider reasons — never silent noise.
        self.ledger.append("music_generation_failed", {
            "topic": topic, "quality": quality,
            "provider_errors": (result.error or "unknown error")[:500] if result else "no result",
        }, self.settings.tenant_id, "BELAL")
        return None

    #: Uploaded audio extensions the ingest path accepts (ffmpeg-readable).
    UPLOAD_AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")
    MAX_UPLOAD_BYTES = 150 * 1024 * 1024

    def import_uploaded_music(self, filename: str, data: bytes, title: str = "",
                              genre: str = "cinematic", mood: str = "inspirational",
                              lyrics: str = "", source: str = "owner_upload",
                              license_note: str = "",
                              uploader: str | None = None) -> MusicAsset:
        """Ingest an owner-supplied audio file (e.g. Suno web export, free-library
        track) as a first-class MusicAsset.

        The file is validated as real audio, mastered to delivery spec
        (-14 LUFS, 48kHz stereo), and queued for owner review exactly like a
        generated track — same gate, same approve → publish path. Raises
        ValueError/GovernanceViolation on bad input.
        """
        import hashlib
        if not data:
            raise ValueError("uploaded file is empty")
        if len(data) > self.MAX_UPLOAD_BYTES:
            raise ValueError(f"uploaded file exceeds {self.MAX_UPLOAD_BYTES // (1024*1024)}MB limit")
        ext = Path(filename or "").suffix.lower()
        if ext not in self.UPLOAD_AUDIO_EXTENSIONS:
            raise ValueError(f"unsupported audio type {ext or '(none)'}; use mp3 or wav")

        asset_id = f"music-{uuid.uuid4().hex[:12]}"
        music_dir = Path(self.settings.data_dir) / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        source_path = music_dir / f"{asset_id}.orig{ext}"
        source_path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()

        # Validate: real probeable audio with content (not empty/corrupt).
        probe = self._probe_audio_file(source_path)
        if not probe:
            source_path.unlink(missing_ok=True)
            raise ValueError("file is not readable audio (probe failed)")
        duration = int(probe.get("duration", 0) or 0)
        if duration <= 0:
            source_path.unlink(missing_ok=True)
            raise ValueError("audio duration is zero")

        asset = MusicAsset(
            asset_id=asset_id,
            tenant_id=self.settings.tenant_id,
            title=title.strip() or Path(filename).stem[:80],
            genre=genre, mood=mood,
            duration_seconds=duration,
            language="en",
            prompt=f"uploaded: {title.strip() or filename}",
            lyrics=lyrics,
            provider="manual_upload",
            quality="high",
            media_manifest={},
            metadata={
                "source": source,
                "license_note": license_note,
                "uploader": uploader or self.settings.owner_actor,
                "original_filename": filename,
                "source_sha256": digest,
            },
        )
        asset.transition(AssetStatus.COMPOSING)
        asset.transition(AssetStatus.MIXING)
        try:
            mastered = music_dir / f"{asset_id}.mastered.wav"
            result = self.enhancer.master_music(source_path, mastered)
            asset.audio_path = str(result.output_path)
            asset.media_manifest["enhancement"] = result.to_dict()
        except EnhancementError as exc:
            asset.audio_path = str(source_path)
            asset.media_manifest["enhancement"] = {"error": str(exc)}
        asset.media_manifest["source_audio_path"] = str(source_path)
        asset.transition(AssetStatus.AWAITING_OWNER)
        self.music_assets[asset.asset_id] = asset
        self.store.save_music(asset)
        self._record_generation_cost("music", asset.asset_id, "manual_upload")
        self.ledger.append("music_uploaded", {
            "asset_id": asset.asset_id, "source": source,
            "duration_seconds": duration, "sha256": digest[:16],
        }, self.settings.tenant_id, "BELAL")
        return asset

    @staticmethod
    def _probe_audio_file(path: Path) -> dict[str, Any] | None:
        """ffprobe a file; None when unreadable. No exceptions escape."""
        import json as _json  # pylint: disable=reimported  # local scope shadows module json; alias avoids the clash
        import subprocess as _subprocess
        try:
            out = _subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=sample_rate,channels,codec_name",
                 "-show_entries", "format=duration",
                 "-of", "json", str(path)],
                check=True, timeout=30, capture_output=True, text=True,
            ).stdout
            data = _json.loads(out)
            stream = (data.get("streams") or [{}])[0]
            return {
                "duration": float(data.get("format", {}).get("duration", 0) or 0),
                "sample_rate": int(stream.get("sample_rate", 0) or 0),
                "channels": int(stream.get("channels", 0) or 0),
                "codec": stream.get("codec_name", ""),
            }
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # External video ingest → unlisted upload → owner review → public    #
    # ------------------------------------------------------------------ #

    #: Video container extensions accepted by the external ingest path.
    INGEST_VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".mkv")
    #: Hard ceiling on an ingested source file (2 GiB).
    MAX_INGEST_BYTES = 2 * 1024 * 1024 * 1024
    #: Quota cost of a single ``videos.insert`` call, in Data API units.
    VIDEOS_INSERT_QUOTA_UNITS = 1600
    #: Default daily quota for a Google Cloud project, in Data API units.
    YOUTUBE_DAILY_QUOTA_UNITS = 10000
    #: The known-good reference video used to detect the unverified-project lock.
    YOUTUBE_REFERENCE_VIDEO_ID = "NHXdNQzF5m0"
    #: Scope required by ``videos.update`` (privacy flip), full and short form.
    FORCE_SSL_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
    FORCE_SSL_SCOPE_SHORT = "youtube.force-ssl"

    def ingest_external_video(self, source_path: Path | str, topic: str, title: str = "",
                              pillar: str = "education", language: str = "en",
                              source: str = "external_file") -> ContentAsset:
        """Bring an externally produced video into the pipeline as a first-class asset.

        The source file is validated, hashed, copied into ``data/videos/`` and
        re-hashed; the managed copy is what every later stage reads, so
        provenance points at an app-controlled artifact rather than the owner's
        working directory. The asset lands in ``awaiting_owner`` — the owner
        gate is unchanged, and no publish path can be reached without it.

        Raises ``ValueError`` on any validation failure; nothing is left behind.
        """
        import shutil

        source_file = Path(source_path)
        if not source_file.exists():
            raise ValueError(f"source file not found: {source_file}")
        if not source_file.is_file():
            raise ValueError(f"source path is not a file: {source_file}")
        size_bytes = source_file.stat().st_size
        if size_bytes <= 0:
            raise ValueError("source file is empty")
        if size_bytes > self.MAX_INGEST_BYTES:
            raise ValueError(f"source file exceeds {self.MAX_INGEST_BYTES // (1024 ** 3)}GB ingest limit")
        extension = source_file.suffix.lower()
        if extension not in self.INGEST_VIDEO_EXTENSIONS:
            raise ValueError(
                f"unsupported video type {extension or '(none)'}; "
                f"use {', '.join(self.INGEST_VIDEO_EXTENSIONS)}"
            )

        asset_id = f"video-{uuid.uuid4().hex[:12]}"
        videos_dir = Path(self.settings.data_dir) / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)
        managed_path = videos_dir / f"{asset_id}.mp4"

        source_sha256 = sha256_file(source_file)
        shutil.copyfile(source_file, managed_path)
        managed_sha256 = sha256_file(managed_path)
        if managed_sha256 != source_sha256:
            managed_path.unlink(missing_ok=True)
            raise ValueError("managed copy hash mismatch — ingest aborted")

        probe = probe_video_file(managed_path)
        if not probe or float(probe.get("duration", 0) or 0) <= 0:
            managed_path.unlink(missing_ok=True)
            raise ValueError("file is not readable video (probe failed)")

        asset = ContentAsset(
            asset_id=asset_id,
            tenant_id=self.settings.tenant_id,
            topic=topic.strip() or managed_path.stem,
            pillar=pillar or "education",
            language=Language(language),
            created_by="MIRA",
            provenance=[f"external_ingest:{source_file}", f"source_sha256:{source_sha256}"],
            media_manifest={
                "video_path": str(managed_path),
                "provider": "external_ingest",
                "provider_attempts": ["external_ingest"],
                "duration": float(probe["duration"]),
                "resolution": resolution_label(int(probe["width"]), int(probe["height"])),
                "scenes": 1,
                "chapters": [],
                "source_path": str(source_file),
                "source_sha256": source_sha256,
                "managed_sha256": managed_sha256,
                "size_bytes": int(probe["size_bytes"]),
                "ffprobe": probe,
            },
            metadata={
                "title": title.strip(),
                "source": source,
                "ingest_source": "external_file",
                "original_filename": source_file.name,
                "ingested_by": self.settings.owner_actor,
            },
        )
        # Walk the sanctioned chain rather than jumping the state machine.
        asset.transition(AssetStatus.RESEARCHED)
        asset.transition(AssetStatus.SCRIPTED)
        asset.transition(AssetStatus.FACT_CHECKED)
        asset.transition(AssetStatus.PRODUCED)
        asset.transition(AssetStatus.AWAITING_OWNER)

        seo = self._draft_seo_metadata(asset, title)
        if seo is not None:
            asset.media_manifest["seo_metadata"] = seo

        # Informative only: the hard gate stays at owner approval, which re-runs
        # the same check and refuses to pass on any issue.
        check = self.quality_gates.check_media_asset(asset, str(managed_path), "video")
        asset.quality_score, asset.quality_issues = check.score, check.issues

        self.assets[asset.asset_id] = asset
        self.store.save_asset(asset)
        self.ledger.append("external_video_ingested", {
            "asset_id": asset.asset_id,
            "source_path": str(source_file),
            "source_sha256": source_sha256,
            "managed_path": str(managed_path),
            "managed_sha256": managed_sha256,
            "size_bytes": int(probe["size_bytes"]),
            "duration": float(probe["duration"]),
            "resolution": asset.media_manifest["resolution"],
            "quality_score": check.score,
            "quality_passed": check.passed,
        }, asset.tenant_id, "MIRA")
        return asset

    def _draft_seo_metadata(self, asset: ContentAsset, title: str = "") -> dict[str, Any] | None:
        """Best-effort SEO draft. Pure function, no credentials, never raises."""
        try:
            seo = YouTubeUploadService.generate_seo_metadata(
                content_type="video",
                topic=title.strip() or asset.topic,
                pillar=asset.pillar,
                language=asset.language.value,
            )
        except Exception:
            return None
        if title.strip():
            seo["title"] = title.strip()[:100]
        return seo

    def _resolve_seo_metadata(self, asset: ContentAsset) -> dict[str, Any]:
        """The metadata to upload with: owner-edited draft if present, else a fresh draft."""
        stored = asset.media_manifest.get("seo_metadata")
        if isinstance(stored, dict) and str(stored.get("title") or "").strip():
            tags = stored.get("tags") or []
            return {
                "title": str(stored["title"])[:100],
                "description": str(stored.get("description") or "")[:5000],
                "tags": [str(tag) for tag in tags][:30],
                "category_id": str(stored.get("category_id") or "27"),
            }
        return YouTubeUploadService.generate_seo_metadata(
            content_type="video",
            topic=str(asset.metadata.get("title") or asset.topic),
            pillar=asset.pillar,
            language=asset.language.value,
        )

    def update_seo_metadata(self, asset_id: str, title: str = "", description: str = "",
                            tags: list[str] | None = None) -> dict[str, Any]:
        """Merge owner edits into ``media_manifest['seo_metadata']``."""
        asset = self.get_asset(asset_id)
        seo = dict(asset.media_manifest.get("seo_metadata") or {})
        if title.strip():
            seo["title"] = title.strip()[:100]
        if description.strip():
            seo["description"] = description.strip()[:5000]
        if tags is not None:
            seo["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()][:30]
        seo.setdefault("category_id", "27")
        asset.media_manifest["seo_metadata"] = seo
        self.store.save_asset(asset)
        self.ledger.append("seo_metadata_updated", {
            "asset_id": asset_id,
            "title": seo.get("title", ""),
            "tag_count": len(seo.get("tags") or []),
        }, asset.tenant_id, "LEO")
        return {"asset_id": asset_id, "seo_metadata": seo}

    def upload_unlisted(self, asset_id: str, approver: str | None = None) -> dict[str, Any]:
        """Upload an owner-approved asset to YouTube as **unlisted**.

        Owner approval, the approval record and the weekly cap are all enforced
        here — this is where the 1600-unit ``videos.insert`` quota is spent.
        Any failure leaves the asset ``approved`` and is ledgered; there is no
        path from this method to a public video.
        """
        asset = self.get_asset(asset_id)
        self.governance.assert_publishable(asset, "youtube", self.queue.get_weekly_count("video"))

        video_path = Path(str(asset.media_manifest.get("video_path") or ""))
        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise GovernanceViolation(f"asset {asset_id} has no readable video preview")

        seo = self._resolve_seo_metadata(asset)
        try:
            service = self._get_youtube_service()
            result = service.upload_video(
                video_path=video_path,
                title=seo["title"],
                description=seo.get("description", ""),
                tags=list(seo.get("tags") or []),
                category_id=seo.get("category_id", "27"),
                privacy_status="unlisted",
            )
        except Exception as exc:
            self.ledger.append("video_upload_failed", {
                "asset_id": asset_id,
                "error": str(exc)[:500],
            }, asset.tenant_id, "LEO")
            raise

        asset.media_manifest["youtube_video_id"] = result["video_id"]
        asset.media_manifest["youtube_url"] = result["video_url"]
        asset.media_manifest["privacy_status"] = "unlisted"
        asset.media_manifest["seo_metadata"] = seo
        asset.transition(AssetStatus.UPLOADED_UNLISTED)
        self.store.save_asset(asset)
        payload = {
            "asset_id": asset_id,
            "youtube_video_id": result["video_id"],
            "youtube_url": result["video_url"],
            "privacy_status": "unlisted",
            "approval_id": asset.approval_id,
            "approver": approver or self.settings.owner_actor,
            "title": seo["title"],
        }
        self.ledger.append("video_uploaded_unlisted", payload, asset.tenant_id, "LEO")
        return payload

    def go_public(self, asset_id: str, approver: str | None = None) -> dict[str, Any]:
        """Flip an unlisted asset to **public** via ``videos.update``, then verify.

        Owner-only and fail-closed: if the API reports anything other than
        ``public`` after the update — the signature of Google's unverified
        API-project lock — the asset stays ``uploaded_unlisted`` and the caller
        is told to publish manually from YouTube Studio.
        """
        asset = self.get_asset(asset_id)
        self.governance.assert_owner(approver or self.settings.owner_actor)
        if asset.status is not AssetStatus.UPLOADED_UNLISTED:
            raise GovernanceViolation(f"asset must be uploaded_unlisted before going public, got {asset.status}")
        if not asset.approval_id:
            raise GovernanceViolation("missing owner approval record")

        video_id = str(asset.media_manifest.get("youtube_video_id") or "")
        if not video_id:
            raise GovernanceViolation("asset has no youtube_video_id to flip")

        try:
            service = self._get_youtube_service()
            service.update_video_privacy(video_id, "public")
            status = service.get_video_status(video_id)
        except Exception as exc:
            self.ledger.append("go_public_failed", {
                "asset_id": asset_id, "video_id": video_id, "error": str(exc)[:500],
            }, asset.tenant_id, "LEO")
            raise GovernanceViolation(f"youtube privacy flip failed: {exc}") from exc

        if str(status.get("privacy_status") or "") != "public":
            self.ledger.append("go_public_failed", {
                "asset_id": asset_id, "video_id": video_id,
                "privacy_status": str(status.get("privacy_status") or ""),
            }, asset.tenant_id, "LEO")
            raise GovernanceViolation("youtube private-lock suspected; manual YouTube Studio publish required")

        asset.media_manifest["privacy_status"] = "public"
        asset.transition(AssetStatus.PUBLISHED)
        self.store.save_asset(asset)
        payload = {
            "asset_id": asset_id,
            "youtube_video_id": video_id,
            "youtube_url": asset.media_manifest.get("youtube_url", ""),
            "privacy_status": "public",
            "approver": approver or self.settings.owner_actor,
        }
        self.ledger.append("video_published_public", payload, asset.tenant_id, "LEO")
        return payload

    def _granted_youtube_scopes(self) -> list[str]:
        """Scopes actually recorded for the YouTube connection (short or full form)."""
        record = self.connections.get("youtube") or {}
        scopes = record.get("scopes")
        if isinstance(scopes, list) and scopes:
            return [str(scope) for scope in scopes]
        token_path = Path(self.settings.data_dir) / "youtube_token.json"
        if token_path.is_file():
            try:
                raw = json.loads(token_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            stored = raw.get("scopes")
            if isinstance(stored, list):
                return [str(scope) for scope in stored]
        return []

    def _oembed_is_public(self, video_id: str) -> dict[str, Any]:
        """oEmbed probe: HTTP 200 means the video is publicly visible.

        Used to decide whether the unverified-project private-lock applies,
        before spending any upload quota. Never raises.
        """
        import requests

        try:
            response = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
                timeout=10,
            )
        except Exception as exc:
            return {"ok": False, "public": None, "status_code": None, "error": str(exc)[:300]}
        return {
            "ok": response.status_code == 200,
            "public": response.status_code == 200,
            "status_code": response.status_code,
        }

    @staticmethod
    def _preflight_file(path: Path) -> dict[str, Any]:
        """Integrity evidence for a candidate file: size, SHA-256, ffprobe."""
        try:
            if not path.is_file():
                return {"exists": False, "size_bytes": 0, "sha256": None, "ffprobe": None}
            return {
                "exists": True,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "ffprobe": probe_video_file(path),
            }
        except OSError as exc:
            return {"exists": False, "size_bytes": 0, "sha256": None, "ffprobe": None, "error": str(exc)}

    def preflight_youtube_publish(self, video_path: Path | None = None,
                                  reference_video_id: str = YOUTUBE_REFERENCE_VIDEO_ID) -> dict[str, Any]:
        """Read-only readiness check before an upload spends quota.

        Reports: (a) token validity via ``channels.list``; (b) whether the
        granted scopes include ``youtube.force-ssl`` (required for the flip);
        (c) whether the reference video is publicly visible, which tells us if
        the unverified-project private-lock applies; (d) quota arithmetic; and
        (e) file integrity when a path is supplied.
        """
        report: dict[str, Any] = {
            "checked_at": now_iso(),
            "video_path": str(video_path) if video_path is not None else None,
            "reference_video_id": reference_video_id,
            "youtube_upload_enabled": bool(self.settings.youtube_upload_enabled),
            "quota": {
                "videos_insert_units": self.VIDEOS_INSERT_QUOTA_UNITS,
                "default_daily_units": self.YOUTUBE_DAILY_QUOTA_UNITS,
                "uploads_per_day": self.YOUTUBE_DAILY_QUOTA_UNITS // self.VIDEOS_INSERT_QUOTA_UNITS,
            },
        }

        channel: dict[str, Any] = {"ok": False, "error": "youtube upload not enabled"}
        if self.settings.youtube_upload_enabled:
            try:
                channel = self._get_youtube_service().check_channel_access()
            except Exception as exc:
                channel = {"ok": False, "error": str(exc)[:300]}
        report["channel_access"] = channel

        granted = self._granted_youtube_scopes()
        report["granted_scopes"] = granted
        report["force_ssl_scope_granted"] = any(
            scope in (self.FORCE_SSL_SCOPE, self.FORCE_SSL_SCOPE_SHORT) for scope in granted
        )

        report["reference_video"] = self._oembed_is_public(reference_video_id)
        report["reference_video_public"] = report["reference_video"].get("public")

        if video_path is not None:
            report["file"] = self._preflight_file(Path(video_path))

        report["ok"] = bool(channel.get("ok")) and bool(report["force_ssl_scope_granted"])
        return report

    def generate_podcast(self, topic: str, script: str, host_voice: str = "en-US-AriaNeural",
                         guest_voice: str | None = None, duration_seconds: int = 1800,
                         format: str = "dialogue",  # pylint: disable=redefined-builtin  # public API parameter (media format)
                         quality: str = "high",
                         language: str = "en", host_name: str = "Host",
                         guest_name: str = "Guest") -> PodcastAsset | None:
        estimated = self.provider_registry.estimated_cost_for("tts", quality)
        self.governance.assert_autonomous_generation_allowed(
            "podcast", self.queue.get_weekly_count("podcast"), estimated
        )
        result = self.podcast_engine.generate(
            topic=topic, script=script, host_voice=host_voice,
            guest_voice=guest_voice, duration_seconds=duration_seconds, format=format,
            quality=quality, language=language,
            host_name=host_name, guest_name=guest_name,
        )
        if result.success and result.asset:
            self._enhance_podcast_asset(result.asset)
            self.podcast_assets[result.asset.asset_id] = result.asset
            self.store.save_podcast(result.asset)
            self._record_generation_cost("podcast", result.asset.asset_id, result.tts_provider_used)
            self.ledger.append("podcast_generated", {
                "asset_id": result.asset.asset_id,
                "tts_provider": result.tts_provider_used,
            }, self.settings.tenant_id, "ZACK")
            return result.asset
        return None

    def generate_video(self, topic: str, prompt: str, duration: int = 5,
                       quality: str = "high", narration: str | None = None,
                       music_mode: str = "ambient",
                       progress_cb: Any = None,
                       preferred_provider: str | None = None) -> ContentAsset | None:
        estimated = self.provider_registry.estimated_cost_for("video", quality)
        self.governance.assert_autonomous_generation_allowed(
            "video", self.queue.get_weekly_count("video"), estimated
        )
        result = self.video_engine.generate(
            topic=topic, prompt=prompt, duration=duration, quality=quality,
            narration=narration, music_mode=music_mode, progress_cb=progress_cb,
            preferred_provider=preferred_provider,
        )
        if result.success and result.asset:
            if progress_cb:
                progress_cb("mastering", 93.0)
            self._enhance_video_asset(result.asset)
            self.assets[result.asset.asset_id] = result.asset
            self.store.save_asset(result.asset)
            self._record_generation_cost("video", result.asset.asset_id, result.provider_used)
            self.ledger.append("video_generated", {
                "asset_id": result.asset.asset_id,
                "provider": result.provider_used,
            }, self.settings.tenant_id, "BELAL")
            return result.asset
        return None

    # ------------------------------------------------------------------ #
    # Background video jobs (long-form: 60s+ renders run for many minutes) #
    # ------------------------------------------------------------------ #

    MAX_VIDEO_JOB_SECONDS = 600

    def quote_video_job(self, duration: int, quality: str = "high",
                        provider: str | None = None) -> dict[str, Any]:
        """Price a long-form render BEFORE spending anything.

        Resolves the provider the engine would pick (or the preferred one),
        quotes per-second cloud cost, and compares against the manually
        recorded free-credit pool. Untracked providers (no pool recorded)
        are allowed through — enforcement only bites once you record a
        balance, so testing is never blocked by the budgeter.
        """
        candidates = self.provider_registry.configured_media_candidates("video", provider, quality)
        from .providers import without_local_pixels
        candidates = without_local_pixels(candidates, self.settings)
        name = provider or (candidates[0].name if candidates else "ken_burns")
        est_cents = self.finance.quote_video_seconds(name, duration)
        free_remaining = self.finance.get_free_cents(name)
        affordable = free_remaining is None or est_cents <= free_remaining
        return {
            "provider": name, "duration": duration,
            "estimated_cents": est_cents,
            "estimated_usd": round(est_cents / 100, 2),
            "free_remaining_cents": free_remaining,
            "affordable": affordable,
        }

    def submit_video_job(self, topic: str, prompt: str, duration: int = 180,
                         quality: str = "high", narration: str | None = None,
                         music_mode: str = "ambient",
                         preferred_provider: str | None = None) -> VideoJob:
        """Queue a long-form video render as a background job.

        Returns immediately with a job the cockpit polls. Raises on invalid
        input, unaffordable quote, or governance block so bad jobs never
        enter the queue.
        """
        if not (topic or "").strip():
            raise ValueError("topic is required")
        if duration < 60:
            raise ValueError("jobs are for 60s+ videos; use /api/generate/video for shorts")
        if duration > self.MAX_VIDEO_JOB_SECONDS:
            raise ValueError(f"duration capped at {self.MAX_VIDEO_JOB_SECONDS}s")
        quote = self.quote_video_job(duration, quality, preferred_provider)
        if not quote["affordable"]:
            raise ValueError(
                f"quoted ${quote['estimated_usd']:.2f} on {quote['provider']} exceeds "
                f"recorded free balance ${quote['free_remaining_cents'] / 100:.2f} — "
                f"shorten the video, pick stock footage, or top up")
        estimated = self.provider_registry.estimated_cost_for("video", quality)
        self.governance.assert_autonomous_generation_allowed(
            "video", self.queue.get_weekly_count("video"), estimated
        )
        job = self.jobs.submit_video(topic=topic, prompt=prompt or topic, duration=duration,
                                     quality=quality, narration=narration, music_mode=music_mode,
                                     preferred_provider=preferred_provider)
        self.ledger.append("video_job_submitted", {**job.to_dict(), "quote": quote},
                           self.settings.tenant_id, "LEO")
        self.jobs.run(job.job_id, self._run_video_job)
        return job

    def _run_video_job(self, job: VideoJob, progress: Any) -> None:
        """Worker body: full pipeline with stage progress, then persist."""
        asset = self.generate_video(
            topic=job.topic, prompt=job.prompt, duration=job.duration,
            quality=job.quality, narration=job.narration, music_mode=job.music_mode,
            progress_cb=progress, preferred_provider=job.preferred_provider,
        )
        if not asset:
            raise RuntimeError("video generation failed (see provider errors in health panel)")
        check = self.quality_gates.check_media_asset(
            asset, asset.media_manifest.get("video_path"), "video")
        asset.quality_score, asset.quality_issues = check.score, check.issues
        self.store.save_asset(asset)
        self.jobs.update(job.job_id, asset_id=asset.asset_id)
        self.ledger.append("video_job_completed", {
            "job_id": job.job_id, "asset_id": asset.asset_id,
            "quality_score": check.score, "quality_passed": check.passed,
        }, self.settings.tenant_id, "BELAL")

    def get_video_job(self, job_id: str) -> VideoJob:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(f"unknown job: {job_id}")
        return job

    def list_video_jobs(self) -> list[VideoJob]:
        return self.jobs.list_jobs()

    def approve_music(self, asset_id: str, approver: str | None = None) -> dict[str, Any]:
        asset = self.music_assets.get(asset_id)
        if not asset:
            raise KeyError(f"unknown music asset: {asset_id}")
        self._assert_preview_exists(asset.audio_path)
        quality = self.quality_gates.check_media_asset(asset, asset.audio_path, "music")
        asset.quality_score, asset.quality_issues = quality.score, quality.issues
        if not quality.passed:
            raise GovernanceViolation(f"owner approval blocked by quality gate: {', '.join(quality.issues)}")
        self.governance.approve(
            asset, requested_by="BELAL",
            approver=approver or self.settings.owner_actor,
        )
        self.store.save_music(asset)
        self.ledger.append("music_approved", {"asset_id": asset_id}, self.settings.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset_id, "status": "approved", "quality_score": quality.score}

    def approve_podcast(self, asset_id: str, approver: str | None = None) -> dict[str, Any]:
        asset = self.podcast_assets.get(asset_id)
        if not asset:
            raise KeyError(f"unknown podcast asset: {asset_id}")
        self._assert_preview_exists(asset.audio_path)
        quality = self.quality_gates.check_media_asset(asset, asset.audio_path, "podcast")
        asset.quality_score, asset.quality_issues = quality.score, quality.issues
        if not quality.passed:
            raise GovernanceViolation(f"owner approval blocked by quality gate: {', '.join(quality.issues)}")
        self.governance.approve(
            asset, requested_by="ZACK",
            approver=approver or self.settings.owner_actor,
        )
        self.store.save_podcast(asset)
        self.ledger.append("podcast_approved", {"asset_id": asset_id}, self.settings.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset_id, "status": "approved", "quality_score": quality.score}

    def publish_music(self, asset_id: str, channel: str = "youtube") -> dict[str, Any]:
        asset = self.music_assets.get(asset_id)
        if not asset:
            raise KeyError(f"unknown music asset: {asset_id}")
        self.governance.assert_publishable_music(asset, self.queue.get_weekly_count("music"))

        youtube_result = None
        if channel == "youtube" and self.settings.youtube_upload_enabled:
            youtube_service = self._get_youtube_service()
            audio_path = Path(asset.audio_path or "")
            if audio_path.exists():
                # Generate SEO metadata for music
                seo = youtube_service.generate_seo_metadata(
                    content_type="music",
                    topic=asset.title,
                    pillar=asset.genre,
                    language=asset.language,
                    extra_tags=[asset.genre, asset.mood, "background music", "royalty free"],
                    genre=asset.genre,
                    mood=asset.mood,
                )
                youtube_result = youtube_service.upload_audio_as_video(
                    audio_path=audio_path,
                    title=seo["title"],
                    description=seo["description"],
                    tags=seo["tags"],
                    category_id=seo["category_id"],
                    privacy_status="private",
                )
                asset.media_manifest = asset.media_manifest or {}
                asset.media_manifest["youtube_video_id"] = youtube_result["video_id"]
                asset.media_manifest["youtube_url"] = youtube_result["video_url"]
                asset.media_manifest["seo_metadata"] = seo

        asset.transition(AssetStatus.PUBLISHED)
        self.store.save_music(asset)
        self.ledger.append(
            "music_published",
            {"asset_id": asset_id, "channel": channel, "youtube": youtube_result},
            self.settings.tenant_id,
            "LEO",
        )
        return {"asset_id": asset_id, "channel": channel, "status": "published", "youtube": youtube_result}

    def publish_podcast(self, asset_id: str, channel: str = "youtube") -> dict[str, Any]:
        asset = self.podcast_assets.get(asset_id)
        if not asset:
            raise KeyError(f"unknown podcast asset: {asset_id}")
        self.governance.assert_publishable_podcast(asset, self.queue.get_weekly_count("podcast"))

        youtube_result = None
        if channel == "youtube" and self.settings.youtube_upload_enabled:
            youtube_service = self._get_youtube_service()
            audio_path = Path(asset.audio_path or "")
            if audio_path.exists():
                # Generate SEO metadata for podcast
                seo = youtube_service.generate_seo_metadata(
                    content_type="podcast",
                    topic=asset.topic,
                    pillar=asset.format,
                    language=asset.language,
                    extra_tags=[asset.format, "podcast", "education", "audio"],
                )
                youtube_result = youtube_service.upload_audio_as_video(
                    audio_path=audio_path,
                    title=seo["title"],
                    description=seo["description"],
                    tags=seo["tags"],
                    category_id=seo["category_id"],
                    privacy_status="private",
                )
                asset.media_manifest = asset.media_manifest or {}
                asset.media_manifest["youtube_video_id"] = youtube_result["video_id"]
                asset.media_manifest["youtube_url"] = youtube_result["video_url"]
                asset.media_manifest["seo_metadata"] = seo

        asset.transition(AssetStatus.PUBLISHED)
        self.store.save_podcast(asset)
        self.ledger.append(
            "podcast_published",
            {"asset_id": asset_id, "channel": channel, "youtube": youtube_result},
            self.settings.tenant_id,
            "LEO",
        )
        return {"asset_id": asset_id, "channel": channel, "status": "published", "youtube": youtube_result}

    def get_queue_status(self) -> dict[str, Any]:
        return {
            "total": self.queue.size(),
            "pending": len(self.queue.get_pending()),
            "ready_to_publish": len(self.queue.get_ready_to_publish()),
            "published": len(self.queue.get_published()),
            "rejected": len(self.queue.get_rejected()),
        }

    def get_finance_status(self) -> dict[str, Any]:
        return {
            "total_costs": self.finance.get_total_costs(),
            "weekly_costs": self.finance.get_weekly_costs(),
            "music_costs": self.finance.get_content_costs("music"),
            "podcast_costs": self.finance.get_content_costs("podcast"),
            "video_costs": self.finance.get_content_costs("video"),
            "provider_rotation": self.provider_registry.rotation.snapshot(),
        }

    def get_health_status(self) -> dict[str, Any]:
        status = self.health_monitor.get_status()
        catalog = {entry["id"]: entry for entry in self.provider_registry.catalog()}
        for content_type, names in self.provider_registry.list_providers().items():
            for name in names:
                entry = catalog.get(name, {})
                status.setdefault(name, {
                    "status": "configured" if entry.get("configured", True) else "unconfigured",
                    "configured": bool(entry.get("configured", True)),
                    "content_type": content_type,
                    "mode": entry.get("mode"),
                    "successes": 0,
                    "failures": 0,
                })
        return status

    def _enhance_music_asset(self, asset: MusicAsset) -> None:
        if not asset.audio_path:
            return
        source = Path(asset.audio_path)
        target = source.with_name(f"{source.stem}.mastered.wav")
        try:
            result = self.enhancer.master_audio(source, target, profile=f"{self.enhancement_profile}_audio")
            asset.audio_path = str(result.output_path)
            asset.media_manifest.update({"source_audio_path": str(source), "enhancement": result.to_dict()})
        except EnhancementError as exc:
            asset.media_manifest.setdefault("enhancement", {})["error"] = str(exc)

    def _enhance_podcast_asset(self, asset: PodcastAsset) -> None:
        if not asset.audio_path:
            return
        source = Path(asset.audio_path)
        target = source.with_name(f"{source.stem}.mastered.wav")
        try:
            result = self.enhancer.master_audio(source, target, profile=f"{self.enhancement_profile}_audio")
            asset.audio_path = str(result.output_path)
            asset.media_manifest.update({"source_audio_path": str(source), "enhancement": result.to_dict()})
        except EnhancementError as exc:
            asset.media_manifest.setdefault("enhancement", {})["error"] = str(exc)

    def _enhance_video_asset(self, asset: ContentAsset) -> None:
        source_raw = asset.media_manifest.get("video_path")
        if not source_raw:
            return
        source = Path(source_raw)
        target = source.with_name(f"{source.stem}.mastered.mp4")
        try:
            result = self.enhancer.master_video(
                source, target,
                resolution=asset.media_manifest.get("resolution"),
                profile=f"{self.enhancement_profile}_video",
            )
            asset.media_manifest["video_path"] = str(result.output_path)
            asset.media_manifest["source_video_path"] = str(source)
            asset.media_manifest["enhancement"] = result.to_dict()
        except EnhancementError as exc:
            asset.media_manifest.setdefault("enhancement", {})["error"] = str(exc)

    def _record_generation_cost(self, content_type: str, asset_id: str, provider: str) -> None:
        capability = self.provider_registry.rotation.capability(provider)
        estimated_cents = capability.estimated_cents if capability else 0
        description = "local/offline generation" if estimated_cents == 0 else "cloud provider generation"
        event = CostEvent(
            event_id=f"cost-{asset_id}", tenant_id=self.settings.tenant_id,
            stage="generation", provider=provider, amount_cents=estimated_cents,
            description=description,
        )
        self.finance.log_cost(provider, content_type, asset_id, credits=1, estimated_cents=estimated_cents)
        self.store.save_cost(event)

    @staticmethod
    def _assert_preview_exists(raw_path: str | None) -> None:
        if not raw_path:
            raise GovernanceViolation("owner approval blocked: no generated preview exists")
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.is_file() or path.stat().st_size == 0:
            raise GovernanceViolation("owner approval blocked: generated preview is missing or empty")

    def connection_status(self) -> dict[str, Any]:
        return self.connections.status()

    def save_connection(self, provider: str, values: dict[str, Any]) -> dict[str, Any]:
        result = self.connections.save(provider, values)
        field_map = {
            "openrouter": "openrouter_api_key",
            "groq": "groq_api_key",
            "nvidia_nim": "nvidia_nim_api_key",
            "cerebras": "cerebras_api_key",
            "huggingface": "huggingface_api_key",
            "suno": "suno_api_key",
            "kling": "kling_api_key",
            "seedance": "seedance_api_key",
            "kokoro": "kokoro_api_key",
            "aimlapi": "aimlapi_api_key",
            "kai": "kai_api_key",
            "pexels": "pexels_api_key",
            "pixabay": "pixabay_api_key",
        }
        settings_updates: dict[str, Any] = {}
        if provider in field_map and values.get("api_key"):
            settings_updates[field_map[provider]] = values["api_key"]
        if provider in {"openrouter", "groq", "nvidia_nim", "cerebras", "huggingface"}:
            if values.get("base_url"):
                settings_updates[f"{provider}_base_url"] = values["base_url"]
            if values.get("model"):
                settings_updates[f"{provider}_model"] = values["model"]
        if provider in {"kokoro", "elevenlabs", "suno", "kling", "seedance", "aimlapi", "kai"}:
            if values.get("base_url"):
                settings_updates[f"{provider}_base_url"] = values["base_url"]
        if provider == "youtube":
            if values.get("client_id"):
                settings_updates["youtube_oauth_client_id"] = values["client_id"]
            if values.get("client_secret"):
                settings_updates["youtube_oauth_client_secret"] = values["client_secret"]
        if settings_updates:
            self.settings = replace(self.settings, **settings_updates)
            self.provider_registry = ProviderRegistry(
                self.settings,
                approval_store=self.provider_approvals,
                health_monitor=self.health_monitor,
            )
            self.music_engine._providers = self.provider_registry
            self.podcast_engine._providers = self.provider_registry
            self.video_engine._providers = self.provider_registry
            providers = configured_providers(self.settings)
            clouds = [
                providers[name]
                for name in ("openrouter", "groq", "cerebras", "nvidia_nim", "huggingface")
                if providers[name].configured
            ]
            self.hybrid = HybridRouter(self.governance, providers["local"], clouds[0] if clouds else None, clouds=clouds)
            self.scripts.local = providers["local"]
            self.scripts.cloud = clouds[0] if clouds else None
            self.scripts.cloud_providers = clouds
        return result

    def youtube_oauth_start(self, redirect_uri: str) -> str:
        return self.connections.youtube_authorization_url(redirect_uri)

    def youtube_oauth_callback(self, code: str, state: str) -> dict[str, Any]:
        result = self.connections.youtube_callback(code, state)
        self.settings = replace(self.settings, youtube_upload_enabled=True)
        self._youtube_service = None
        self._init_youtube_service()
        return result
