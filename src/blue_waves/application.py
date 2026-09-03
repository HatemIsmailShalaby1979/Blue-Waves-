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
from .providers import DeferredMotionProvider, ProviderHealthMonitor, ProviderRegistry, configured_providers
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
        saved = self.connections._read()
        overrides = {
            "openrouter_api_key": saved.get("openrouter", {}).get("api_key"),
            "groq_api_key": saved.get("groq", {}).get("api_key"),
            "nvidia_nim_api_key": saved.get("nvidia_nim", {}).get("api_key"),
            "suno_api_key": saved.get("suno", {}).get("api_key"),
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
        providers = configured_providers(self.settings)
        self.local_provider = providers["local"]
        cloud_provider = next((providers[name] for name in ("openrouter", "groq", "nvidia_nim") if providers[name].configured), None)
        self.hybrid = HybridRouter(self.governance, self.local_provider, cloud_provider)
        self.research = ResearchEngine()
        self.scripts = ScriptEngine(self.local_provider, cloud_provider, self.governance)
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
        self.provider_registry = ProviderRegistry(self.settings)
        self.health_monitor = ProviderHealthMonitor()
        self.finance = FinanceEngine()
        self.music_engine = MusicEngine(self.settings, self.governance, self.provider_registry, self.health_monitor)
        self.podcast_engine = PodcastEngine(self.settings, self.governance, self.provider_registry, self.health_monitor)
        self.video_engine = VideoEngine(self.settings, self.governance, self.provider_registry, self.health_monitor)
        self.queue = ContentQueue(self.settings)
        self.scheduler = Scheduler(self.settings, self.governance, self.queue)
        self.quality_gates = QualityGates(self.settings, self.governance)
        self.metacognition = MetacognitiveEngine()
        self.music_assets: dict[str, MusicAsset] = {}
        self.podcast_assets: dict[str, PodcastAsset] = {}
        self._youtube_service: YouTubeUploadService | None = None
        self._init_youtube_service()
        self._load_persisted_assets()
        for event in self.store.latest_metrics():
            self.metacognition.restore_metric(event)

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
        if "video_path" in asset.media_manifest:
            self._assert_preview_exists(asset.media_manifest.get("video_path"))
        approval = self.governance.approve(
            asset,
            requested_by="LEO",
            approver=approver or self.settings.owner_actor,
            reason=reason,
        )
        self.store.save_asset(asset)
        payload = asdict(approval)
        payload["tier"] = approval.tier.value
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

    def reject_asset(self, asset: ContentAsset, reason: str = "owner rejected") -> dict[str, Any]:
        if asset.status is not AssetStatus.AWAITING_OWNER:
            raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED)
        self.store.save_asset(asset)
        self.ledger.append("asset_rejected", {"asset_id": asset.asset_id, "reason": reason}, asset.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset.asset_id, "status": "rejected", "reason": reason}

    def reject_music(self, asset_id: str, reason: str = "owner rejected") -> dict[str, Any]:
        asset = self.music_assets.get(asset_id)
        if not asset: raise KeyError(f"unknown music asset: {asset_id}")
        if asset.status is not AssetStatus.AWAITING_OWNER: raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED); self.store.save_music(asset)
        self.ledger.append("music_rejected", {"asset_id": asset_id, "reason": reason}, self.settings.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset_id, "status": "rejected", "reason": reason}

    def reject_podcast(self, asset_id: str, reason: str = "owner rejected") -> dict[str, Any]:
        asset = self.podcast_assets.get(asset_id)
        if not asset: raise KeyError(f"unknown podcast asset: {asset_id}")
        if asset.status is not AssetStatus.AWAITING_OWNER: raise GovernanceViolation(f"asset is not awaiting owner approval: {asset.status}")
        asset.transition(AssetStatus.REJECTED); self.store.save_podcast(asset)
        self.ledger.append("podcast_rejected", {"asset_id": asset_id, "reason": reason}, self.settings.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset_id, "status": "rejected", "reason": reason}

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
            "version": "0.2.0",
            "tenant_id": self.settings.tenant_id,
            "codex_adapter": type(self.codex).__name__,
            "ledger_intact": integrity,
            "ledger_message": message,
            "cloud_budget_cents": self.settings.monthly_cloud_cents,
            "cloud_motion": "deferred_until_verified_provider",
            "hybrid_motion_route": self.hybrid.route(Stage.MOTION).mode,
            "queue_size": self.queue.size(),
            "music_assets": len(self.music_assets),
            "podcast_assets": len(self.podcast_assets),
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
        self.governance.assert_autonomous_generation_allowed(
            "music", self.queue.get_weekly_count("music"), 0
        )
        result = self.music_engine.generate(
            topic=topic, genre=genre, mood=mood,
            duration_seconds=duration_seconds, quality=quality,
        )
        if result.success and result.asset:
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
                         duration_seconds: int = 1800, quality: str = "high") -> PodcastAsset | None:
        self.governance.assert_autonomous_generation_allowed(
            "podcast", self.queue.get_weekly_count("podcast"), 0
        )
        result = self.podcast_engine.generate(
            topic=topic, script=script, host_voice=host_voice,
            duration_seconds=duration_seconds, quality=quality,
        )
        if result.success and result.asset:
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
                       quality: str = "high") -> ContentAsset | None:
        self.governance.assert_autonomous_generation_allowed(
            "video", self.queue.get_weekly_count("video"), 0
        )
        result = self.video_engine.generate(
            topic=topic, prompt=prompt, duration=duration, quality=quality,
        )
        if result.success and result.asset:
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
        approval = self.governance.approve(
            asset, requested_by="BELAL",
            approver=approver or self.settings.owner_actor,
        )
        self.store.save_music(asset)
        self.ledger.append("music_approved", {"asset_id": asset_id}, self.settings.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset_id, "status": "approved"}

    def approve_podcast(self, asset_id: str, approver: str | None = None) -> dict[str, Any]:
        asset = self.podcast_assets.get(asset_id)
        if not asset:
            raise KeyError(f"unknown podcast asset: {asset_id}")
        self._assert_preview_exists(asset.audio_path)
        approval = self.governance.approve(
            asset, requested_by="ZACK",
            approver=approver or self.settings.owner_actor,
        )
        self.store.save_podcast(asset)
        self.ledger.append("podcast_approved", {"asset_id": asset_id}, self.settings.tenant_id, self.settings.owner_actor)
        return {"asset_id": asset_id, "status": "approved"}

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
                )
                youtube_result = youtube_service.upload_video(
                    video_path=audio_path,
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
                youtube_result = youtube_service.upload_video(
                    video_path=audio_path,
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
        }

    def get_health_status(self) -> dict[str, Any]:
        return self.health_monitor.get_status()

    def _record_generation_cost(self, content_type: str, asset_id: str, provider: str) -> None:
        event = CostEvent(
            event_id=f"cost-{asset_id}", tenant_id=self.settings.tenant_id,
            stage="generation", provider=provider, amount_cents=0,
            description="local/offline generation",
        )
        self.finance.log_cost(provider, content_type, asset_id, credits=0, estimated_cents=0)
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
        field_map = {"openrouter": "openrouter_api_key", "groq": "groq_api_key", "nvidia_nim": "nvidia_nim_api_key", "suno": "suno_api_key"}
        if provider in field_map and values.get("api_key"):
            self.settings = replace(self.settings, **{field_map[provider]: values["api_key"]})
            self.provider_registry = ProviderRegistry(self.settings)
            self.music_engine._providers = self.provider_registry
            self.podcast_engine._providers = self.provider_registry
            self.video_engine._providers = self.provider_registry
        return result

    def youtube_oauth_start(self, redirect_uri: str) -> str:
        return self.connections.youtube_authorization_url(redirect_uri)

    def youtube_oauth_callback(self, code: str, state: str) -> dict[str, Any]:
        return self.connections.youtube_callback(code, state)
