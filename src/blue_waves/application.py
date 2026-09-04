from __future__ import annotations

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

    def __init__(self, settings: Settings | None = None, codex: CodexClient | None = None):
        self.settings = settings or Settings.from_env()
        self.settings.ensure_data_dir()
        self.connections = ConnectionStore(self.settings.data_dir)
        saved = {
            provider: self.connections.get(provider)
            for provider in ("openrouter", "groq", "nvidia_nim", "cerebras", "huggingface", "suno",
                             "kling", "seedance", "kokoro", "aimlapi", "kai", "elevenlabs")
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
        cloud_providers = [providers[name] for name in ("openrouter", "groq", "cerebras", "nvidia_nim", "huggingface") if providers[name].configured]
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
            self.ledger.append("script_created", {"asset_id": asset.asset_id, "language": asset.language.value}, asset.tenant_id, "ZACK")
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
            self.ledger.append("fact_check_blocked", {"asset_id": asset.asset_id, "claim_ids": unsupported}, asset.tenant_id, "ANDY")
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
        self.ledger.append("production_manifest_created", {"asset_id": asset.asset_id, "manifest": manifest}, asset.tenant_id, "BELAL")
        return {"asset_id": asset.asset_id, "ready": True, "manifest": manifest}

    def owner_approve(self, asset: ContentAsset, reason: str = "owner reviewed preview", approver: str | None = None) -> dict[str, Any]:
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

    def record_metric(self, asset: ContentAsset, channel: str, metric: str, value: float, source: str = "owner_import") -> dict[str, Any]:
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

    def record_media_metric(self, asset_id: str, channel: str, metric: str, value: float, source: str = "owner_import") -> dict[str, Any]:
        if asset_id in self.music_assets:
            asset = self.music_assets[asset_id]
            topic, tenant = asset.title, asset.tenant_id
        elif asset_id in self.podcast_assets:
            asset = self.podcast_assets[asset_id]
            topic, tenant = asset.topic, asset.tenant_id
        else:
            raise KeyError(f"unknown media asset: {asset_id}")
        event = MetricEvent(event_id=f"metric-{uuid.uuid4().hex[:10]}", tenant_id=tenant, asset_id=asset_id,
                            channel=channel, metric=metric, value=value, source=source)
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
            asset for asset in list(self.assets.values()) + list(self.music_assets.values()) + list(self.podcast_assets.values())
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
        generator = MediaKitGenerator(metrics=self.store.latest_metrics(),
                                      assets={"videos": len(self.assets), "music": len(self.music_assets), "podcasts": len(self.podcast_assets)})
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
        ET.SubElement(itunes_owner, "{http://www.itunes.com/dtds/podcast-1.0.dtd}email").text = "podcasts@bluewaves.example.com"
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
            ET.SubElement(item, "pubDate").text = datetime.fromisoformat(asset.created_at.replace('Z', '+00:00')).strftime("%a, %d %b %Y %H:%M:%S GMT")
            ET.SubElement(item, "guid").text = asset.asset_id
            
            # Enclosure for audio
            ET.SubElement(item, "enclosure", url=audio_url, type=audio_type, length="0")
            
            # iTunes tags
            ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration").text = str(asset.duration_target_seconds)
            ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType").text = "full"
        
        # Pretty print
        ET.indent(rss, space="  ")
        return ET.tostring(rss, encoding="unicode", xml_declaration=True)

    def reject_asset(self, asset: ContentAsset, reason: str = "owner rejected", approver: str | None = None) -> dict[str, Any]:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        if asset.status is not AssetStatus.AWAITING_OWNER:
            raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED)
        asset.rejection_reason = reason
        self.store.save_asset(asset)
        self.ledger.append("asset_rejected", {"asset_id": asset.asset_id, "reason": reason}, asset.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset.asset_id, "status": "rejected", "reason": reason}

    def reject_music(self, asset_id: str, reason: str = "owner rejected", approver: str | None = None) -> dict[str, Any]:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        asset = self.music_assets.get(asset_id)
        if not asset: raise KeyError(f"unknown music asset: {asset_id}")
        if asset.status is not AssetStatus.AWAITING_OWNER: raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED); asset.rejection_reason = reason; self.store.save_music(asset)
        self.ledger.append("music_rejected", {"asset_id": asset_id, "reason": reason}, self.settings.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset_id, "status": "rejected", "reason": reason}

    def reject_podcast(self, asset_id: str, reason: str = "owner rejected", approver: str | None = None) -> dict[str, Any]:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        asset = self.podcast_assets.get(asset_id)
        if not asset: raise KeyError(f"unknown podcast asset: {asset_id}")
        if asset.status is not AssetStatus.AWAITING_OWNER: raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED); asset.rejection_reason = reason; self.store.save_podcast(asset)
        self.ledger.append("podcast_rejected", {"asset_id": asset_id, "reason": reason}, self.settings.tenant_id, self.settings.owner_actor)
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
        self.ledger.append("music_retry_generated", {"asset_id": asset.asset_id, "parent_asset_id": asset_id, "attempt": asset.attempt, "enhancement": enhancement}, self.settings.tenant_id, "BELAL")
        return asset

    def retry_podcast(self, asset_id: str, enhancement: str = "Improve pacing, diction, and mix balance.",
                      quality: str = "high", approver: str | None = None) -> PodcastAsset:
        self.governance.assert_owner(approver or self.settings.owner_actor)
        previous = self.podcast_assets.get(asset_id)
        if not previous or previous.status is not AssetStatus.REJECTED:
            raise GovernanceViolation("only a rejected podcast preview can be retried")
        asset = self.generate_podcast(
            topic=f"{previous.topic} — enhancement: {enhancement}", script=previous.script,
            host_voice=previous.host_voice, duration_seconds=previous.duration_target_seconds, quality=quality,
        )
        if not asset:
            raise RuntimeError("retry generation failed")
        asset.attempt = previous.attempt + 1
        asset.parent_asset_id = previous.asset_id
        asset.metadata["enhancement"] = enhancement
        self.store.save_podcast(asset)
        self.ledger.append("podcast_retry_generated", {"asset_id": asset.asset_id, "parent_asset_id": asset_id, "attempt": asset.attempt, "enhancement": enhancement}, self.settings.tenant_id, "ZACK")
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
        self.ledger.append("video_retry_generated", {"asset_id": asset.asset_id, "parent_asset_id": asset_id, "attempt": asset.attempt, "enhancement": enhancement}, self.settings.tenant_id, "BELAL")
        return asset

    def intelligence(self) -> dict[str, Any]:
        assets: dict[str, dict[str, Any]] = {}
        for asset in self.assets.values(): assets[asset.asset_id] = {"content_type": "video", "topic": asset.topic, "provider": asset.media_manifest.get("provider", "unknown")}
        for asset in self.music_assets.values(): assets[asset.asset_id] = {"content_type": "music", "topic": asset.title, "provider": asset.provider}
        for asset in self.podcast_assets.values(): assets[asset.asset_id] = {"content_type": "podcast", "topic": asset.topic, "provider": asset.tts_provider}
        return {"performance_ranking": self.metacognition.rank_assets(assets), "shipo": self.metacognition.shipo_recommendations(assets), "approved_memory": self.metacognition.memories()}

    def approve_memory(self, memory_id: str) -> dict[str, Any]:
        candidate = next((item for item in self.metacognition.rank_assets(self._intelligence_assets()) if item["memory_id"] == memory_id), None)
        if not candidate: raise KeyError(f"unknown memory proposal: {memory_id}")
        memory = PerformanceMemory(**candidate)
        approved = self.metacognition.approve(memory); self.store.save_memory(approved)
        self.ledger.append("performance_memory_approved", approved.to_dict(), self.settings.tenant_id, self.settings.owner_actor)
        return approved.to_dict()

    def _intelligence_assets(self) -> dict[str, dict[str, Any]]:
        data = {}
        for a in self.assets.values(): data[a.asset_id] = {"content_type":"video", "topic":a.topic, "provider":a.media_manifest.get("provider", "unknown")}
        for a in self.music_assets.values(): data[a.asset_id] = {"content_type":"music", "topic":a.title, "provider":a.provider}
        for a in self.podcast_assets.values(): data[a.asset_id] = {"content_type":"podcast", "topic":a.topic, "provider":a.tts_provider}
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
            "cloud_motion": [name for name in self.provider_registry.list_providers()["video"] if name != "ken_burns"] or "deferred_until_verified_provider",
            "configured_cloud_motion": [name for name in self.provider_registry.list_providers()["video"] if name != "ken_burns"],
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
        return None

    def generate_podcast(self, topic: str, script: str, host_voice: str = "en-US-AriaNeural",
                         guest_voice: str | None = None, duration_seconds: int = 1800,
                         format: str = "dialogue", quality: str = "high",
                         language: str = "en") -> PodcastAsset | None:
        estimated = self.provider_registry.estimated_cost_for("tts", quality)
        self.governance.assert_autonomous_generation_allowed(
            "podcast", self.queue.get_weekly_count("podcast"), estimated
        )
        result = self.podcast_engine.generate(
            topic=topic, script=script, host_voice=host_voice,
            guest_voice=guest_voice, duration_seconds=duration_seconds, format=format,
            quality=quality, language=language,
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
                       music_mode: str = "ambient") -> ContentAsset | None:
        estimated = self.provider_registry.estimated_cost_for("video", quality)
        self.governance.assert_autonomous_generation_allowed(
            "video", self.queue.get_weekly_count("video"), estimated
        )
        result = self.video_engine.generate(
            topic=topic, prompt=prompt, duration=duration, quality=quality,
            narration=narration, music_mode=music_mode,
        )
        if result.success and result.asset:
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

    def approve_music(self, asset_id: str, approver: str | None = None) -> dict[str, Any]:
        asset = self.music_assets.get(asset_id)
        if not asset:
            raise KeyError(f"unknown music asset: {asset_id}")
        self._assert_preview_exists(asset.audio_path)
        quality = self.quality_gates.check_media_asset(asset, asset.audio_path, "music")
        asset.quality_score, asset.quality_issues = quality.score, quality.issues
        if not quality.passed:
            raise GovernanceViolation(f"owner approval blocked by quality gate: {', '.join(quality.issues)}")
        approval = self.governance.approve(
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
        approval = self.governance.approve(
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
        self.ledger.append("music_published", {"asset_id": asset_id, "channel": channel, "youtube": youtube_result}, self.settings.tenant_id, "LEO")
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
        self.ledger.append("podcast_published", {"asset_id": asset_id, "channel": channel, "youtube": youtube_result}, self.settings.tenant_id, "LEO")
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
        field_map = {"openrouter": "openrouter_api_key", "groq": "groq_api_key", "nvidia_nim": "nvidia_nim_api_key", "cerebras": "cerebras_api_key", "huggingface": "huggingface_api_key", "suno": "suno_api_key", "kling": "kling_api_key", "seedance": "seedance_api_key", "kokoro": "kokoro_api_key", "aimlapi": "aimlapi_api_key", "kai": "kai_api_key"}
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
            clouds = [providers[name] for name in ("openrouter", "groq", "cerebras", "nvidia_nim", "huggingface") if providers[name].configured]
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
