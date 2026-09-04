from __future__ import annotations

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any

from .agents import roster
from .application import BlueWavesApplication
from .cockpit_ui import DASHBOARD_HTML
from .dialogue import supported_languages


class CockpitApp:
    """Web-based control panel for Blue Waves autonomous mode."""

    def __init__(self, application: BlueWavesApplication) -> None:
        self._app = application

    def get_dashboard_data(self) -> dict[str, Any]:
        return {
            "health": self._app.health(),
            "queue": self._app.get_queue_status(),
            "finance": self._app.get_finance_status(),
            "provider_health": self._app.get_health_status(),
            "music_assets": len(self._app.music_assets),
            "podcast_assets": len(self._app.podcast_assets),
            "video_assets": len(self._app.assets),
        }

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        approvals = []
        for asset_id, asset in self._app.music_assets.items():
            if asset.status.value == "awaiting_owner":
                approvals.append({"type": "music", "asset_id": asset_id, "title": asset.title})
        for asset_id, asset in self._app.podcast_assets.items():
            if asset.status.value == "awaiting_owner":
                approvals.append({"type": "podcast", "asset_id": asset_id, "title": asset.title})
        for asset_id, asset in self._app.assets.items():
            if asset.status.value == "awaiting_owner":
                approvals.append({"type": "video", "asset_id": asset_id, "title": asset.topic})
        return approvals

    def approve_content(self, content_type: str, asset_id: str) -> dict[str, Any]:
        try:
            if content_type == "music":
                return self._app.approve_music(asset_id)
            elif content_type == "podcast":
                return self._app.approve_podcast(asset_id)
            elif content_type == "video":
                asset = self._app.get_asset(asset_id)
                return self._app.owner_approve(asset)
        except Exception as exc:
            return {"error": str(exc)}
        return {"error": f"unknown content type: {content_type}"}

    def add_request(self, content_type: str, topic: str, priority: str = "normal",
                    quality: str = "high") -> dict[str, Any]:
        request = self._app.add_content_request(content_type, topic, priority, quality)
        return request.to_dict()

    def get_queue(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._app.queue.get_all()]

    def get_provider_approvals(self) -> dict[str, Any]:
        return self._app.provider_approvals.approval_status()

    def approve_provider(self, provider: str, actor: str = "owner") -> dict[str, Any]:
        return self._app.provider_approvals.approve(provider, actor)

    def revoke_provider(self, provider: str) -> dict[str, Any]:
        ok = self._app.provider_approvals.revoke(provider)
        return {"provider": provider, "revoked": ok}

    def get_provider_catalog(self) -> dict[str, Any]:
        return {
            "catalog": self._app.provider_registry.catalog(),
            "approvals": self._app.provider_approvals.approval_status(),
        }

    def get_rss_feed(self) -> str:
        base_url = self._app.settings.cockpit_public_base_url or f"http://{self._app.settings.cockpit_host}:{self._app.settings.cockpit_port}"
        return self._app.generate_podcast_rss(base_url=base_url)

    def sync_analytics(self) -> dict[str, Any]:
        return self._app.sync_all_published_metrics()

    def run_scheduler(self) -> dict[str, Any]:
        return self._app.run_scheduler_tick()

    def get_metrics(self) -> dict[str, Any]:
        return {"metrics": self._app.store.latest_metrics()}

    def get_media_kit(self) -> dict[str, Any]:
        return self._app.generate_media_kit()

    def get_sponsors(self) -> dict[str, Any]:
        return self._app.sponsor_pipeline()

    def upsert_sponsor(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._app.sponsors.upsert(data)

    def sponsor_email(self, prospect_id: str, company: str = "") -> dict[str, Any]:
        return {"email": self._app.outreach_email_for(prospect_id, company)}

    # ------------------------------------------------------------------ #
    # Expanded cockpit backend                                           #
    # ------------------------------------------------------------------ #

    def get_crew(self) -> dict[str, Any]:
        return {"tenant_id": self._app.settings.tenant_id, "agents": roster(), "tasks": self._derive_tasks()}

    def _derive_tasks(self) -> list[dict[str, Any]]:
        """Build a lightweight task board from assets, queue and scheduler."""
        tasks: list[dict[str, Any]] = []
        for asset_id, asset in self._app.music_assets.items():
            tasks.append({"agent_id": "BELAL", "name": asset.title, "content_type": "music",
                          "asset_id": asset_id, "status": asset.status.value, "attempt": asset.attempt})
        for asset_id, asset in self._app.podcast_assets.items():
            tasks.append({"agent_id": "ZACK", "name": asset.topic, "content_type": "podcast",
                          "asset_id": asset_id, "status": asset.status.value, "attempt": asset.attempt})
        for asset_id, asset in self._app.assets.items():
            tasks.append({"agent_id": "BELAL", "name": asset.topic, "content_type": "video",
                          "asset_id": asset_id, "status": asset.status.value, "attempt": asset.attempt})
        for request in self._app.queue.get_all():
            tasks.append({"agent_id": "MIRA", "name": request.topic, "content_type": request.content_type,
                          "queue_id": request.id, "status": request.stage, "priority": request.priority})
        return tasks

    def get_library(self) -> dict[str, Any]:
        items = []
        for asset_id, asset in self._app.music_assets.items():
            d = asset.to_dict(); d["content_type"] = "music"; d["media_url"] = f"/media/music/{asset_id}"
            d["media_exists"] = self._media_exists(asset.audio_path); items.append(d)
        for asset_id, asset in self._app.podcast_assets.items():
            d = asset.to_dict(); d["content_type"] = "podcast"; d["media_url"] = f"/media/podcast/{asset_id}"
            d["media_exists"] = self._media_exists(asset.audio_path); items.append(d)
        for asset_id, asset in self._app.assets.items():
            d = asset.to_dict(); d["content_type"] = "video"; d["media_url"] = f"/media/video/{asset_id}"
            d["media_exists"] = self._media_exists(asset.media_manifest.get("video_path")); items.append(d)
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"count": len(items), "items": items}

    @staticmethod
    def _media_exists(path: Any) -> bool:
        if not path:
            return False
        p = Path(str(path))
        return p.exists() and p.stat().st_size > 0

    def get_media_path(self, content_type: str, asset_id: str) -> str | None:
        if content_type == "music":
            asset = self._app.music_assets.get(asset_id)
            return asset.audio_path if asset else None
        if content_type == "podcast":
            asset = self._app.podcast_assets.get(asset_id)
            return asset.audio_path if asset else None
        if content_type == "video":
            asset = self._app.assets.get(asset_id)
            return asset.media_manifest.get("video_path") if asset else None
        return None

    def reject_media(self, content_type: str, asset_id: str, reason: str = "owner rejected") -> dict[str, Any]:
        try:
            if content_type == "music":
                return self._app.reject_music(asset_id, reason)
            if content_type == "podcast":
                return self._app.reject_podcast(asset_id, reason)
            if content_type == "video":
                return self._app.reject_asset(self._app.get_asset(asset_id), reason)
        except KeyError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": str(exc)}
        return {"error": f"unknown content type: {content_type}"}

    def retry_media(self, content_type: str, asset_id: str, enhancement: str, quality: str = "high") -> dict[str, Any]:
        try:
            if content_type == "music":
                return self._app.retry_music(asset_id, enhancement, quality).to_dict()
            if content_type == "podcast":
                return self._app.retry_podcast(asset_id, enhancement, quality).to_dict()
            if content_type == "video":
                return self._app.retry_video(asset_id, enhancement, quality).to_dict()
        except Exception as exc:
            return {"error": str(exc)}
        return {"error": f"unknown content type: {content_type}"}

    def publish_media(self, content_type: str, asset_id: str, channel: str = "youtube") -> dict[str, Any]:
        try:
            if content_type == "music":
                return self._app.publish_music(asset_id, channel)
            if content_type == "podcast":
                return self._app.publish_podcast(asset_id, channel)
            if content_type == "video":
                return self._app.publish(self._app.get_asset(asset_id), channel)
        except Exception as exc:
            return {"error": str(exc)}
        return {"error": f"unknown content type: {content_type}"}

    def get_intelligence(self) -> dict[str, Any]:
        return self._app.intelligence()

    def approve_recommendation(self, memory_id: str) -> dict[str, Any]:
        try:
            return self._app.approve_memory(memory_id)
        except Exception as exc:
            return {"error": str(exc)}

    def get_scheduler(self) -> dict[str, Any]:
        return self._app.scheduler.get_stats()

    def get_finance_plan(self) -> dict[str, Any]:
        """Financial plan, targets, timeframe and owner-of-record responsibilities."""
        status = self._app.get_finance_status()
        monthly_cents = self._app.settings.monthly_cloud_cents
        spend_cents = status.get("weekly_costs", 0)
        remaining_cents = max(0, monthly_cents - spend_cents)
        # Get SHEPO's full financial report if available
        shepo_report = {}
        if hasattr(self._app, 'finance') and hasattr(self._app.finance, 'get_shepo_report'):
            shepo_report = self._app.finance.get_shepo_report()
        return {
            "status": status,
            "shepo_report": shepo_report,
            "plan": {
                "budget_monthly_cents": monthly_cents,
                "spent_cents": spend_cents,
                "remaining_cents": remaining_cents,
                "utilization_pct": round((spend_cents / monthly_cents * 100) if monthly_cents else 0, 1),
                "goal": "Maximize media quality while staying within budget and reaching profitability",
                "target": f"{remaining_cents / 100:.2f} USD remaining this month",
                "time_frame": "Monthly budget (resets each month); weekly publish cadence Mon/Wed/Fri",
            },
            "responsibilities": [
                {"role": "SHEPO", "responsible": "Track real costs, project revenue, flag budget overruns, recommend provider ROI optimizations"},
                {"role": "JOE", "responsible": "Track costs, runway and revenue scenarios; surface cost alerts"},
                {"role": "LEO", "responsible": "Queue approved publication; collect platform metrics"},
                {"role": "BELAL", "responsible": "Produce media within quality gates; keep within budget"},
                {"role": "ZACK", "responsible": "Draft scripts; keep generated content accurate"},
                {"role": "KOYOSHU", "responsible": "Recommend reinvestment; flag inefficiency"},
                {"role": "OWNER", "responsible": "Approve budget exceptions and high-cost provider terms"},
            ],
        }

    def get_connections(self) -> dict[str, Any]:
        """Return connection status with secrets hidden (masks/booleans only)."""
        return self._app.connection_status()

    def save_connection(self, provider: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._app.save_connection(provider, values)

    def generate_media(self, content_type: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            if content_type == "music":
                asset = self._app.generate_music(
                    topic=data.get("topic", ""),
                    genre=data.get("genre", "cinematic"),
                    mood=data.get("mood", "inspirational"),
                    duration_seconds=int(data.get("duration_seconds", 180)),
                    quality=data.get("quality", "high"),
                )
            elif content_type == "podcast":
                asset = self._app.generate_podcast(
                    topic=data.get("topic", ""),
                    script=data.get("script", ""),
                    host_voice=data.get("host_voice") or "",
                    guest_voice=data.get("guest_voice"),
                    duration_seconds=int(data.get("duration_seconds", 600)),
                    format=data.get("format", "dialogue"),
                    quality=data.get("quality", "high"),
                    language=data.get("language", "en"),
                )
            elif content_type == "video":
                asset = self._app.generate_video(
                    topic=data.get("topic", ""),
                    prompt=data.get("prompt", data.get("topic", "")),
                    duration=int(data.get("duration", 8)),
                    quality=data.get("quality", "high"),
                    narration=data.get("narration", data.get("script", "")),
                    music_mode=data.get("music_mode", "ambient"),
                )
            else:
                return {"error": f"unknown content type: {content_type}"}
            if not asset:
                return {"error": f"{content_type} generation failed (possibly blocked by policy or provider approval)"}
            d = asset.to_dict(); d["content_type"] = content_type
            return d
        except Exception as exc:
            return {"error": str(exc)}

    def get_quality_breakdown(self, asset_id: str) -> dict[str, Any]:
        """Detailed quality breakdown for the review panel (Phase 8)."""
        try:
            if asset_id in self._app.music_assets:
                asset = self._app.music_assets[asset_id]
                check = self._app.quality_gates.check_media_asset(asset, asset.audio_path, "music")
                return {"asset_id": asset_id, "content_type": "music", "score": check.score,
                        "passed": check.passed, "issues": check.issues, "checked_at": check.checked_at}
            if asset_id in self._app.podcast_assets:
                asset = self._app.podcast_assets[asset_id]
                check = self._app.quality_gates.check_media_asset(asset, asset.audio_path, "podcast")
                return {"asset_id": asset_id, "content_type": "podcast", "score": check.score,
                        "passed": check.passed, "issues": check.issues, "checked_at": check.checked_at}
            if asset_id in self._app.assets:
                asset = self._app.assets[asset_id]
                check = self._app.quality_gates.check_media_asset(
                    asset, asset.media_manifest.get("video_path"), "video")
                return {"asset_id": asset_id, "content_type": "video", "score": check.score,
                        "passed": check.passed, "issues": check.issues, "checked_at": check.checked_at}
        except Exception as exc:
            return {"error": str(exc)}
        return {"error": f"unknown asset: {asset_id}"}

    def get_video_use_status(self) -> dict[str, Any]:
        """video-use integration status (Phase 8)."""
        settings = self._app.settings
        enabled = bool(getattr(settings, "video_use_enabled", False))
        skill_path = Path(getattr(settings, "video_use_skill_path", "vendor/video_use/SKILL.md"))
        if not skill_path.is_absolute():
            skill_path = Path.cwd() / skill_path
        return {
            "enabled": enabled,
            "skill_path": str(getattr(settings, "video_use_skill_path", "")),
            "skill_exists": skill_path.is_file(),
            "editor_available": bool(getattr(self._app.video_engine, "_video_use_editor", None)),
        }

    def trigger_video_use_edit(self, asset_id: str) -> dict[str, Any]:
        """Manually trigger video-use post-production for a video asset."""
        try:
            asset = self._app.assets.get(asset_id)
            if not asset:
                return {"error": f"unknown video asset: {asset_id}"}
            raw_path = asset.media_manifest.get("video_path")
            if not raw_path:
                return {"error": "asset has no video_path"}
            editor = getattr(self._app.video_engine, "_video_use_editor", None)
            if editor is None:
                return {"error": "video-use editor not available (disabled or misconfigured)"}
            result = editor.edit(
                raw_video_path=Path(str(raw_path)),
                transcript_text=asset.topic,
                narration_audio_path=None,
                topic=asset.topic,
                duration=int(asset.media_manifest.get("duration", 8) or 8),
            )
            if not result.success:
                return {"error": result.error or "video-use edit failed", "issues": result.issues}
            # Replace the preview with the post-produced version (cross-drive safe).
            import shutil
            assert result.output_path is not None
            raw = Path(str(raw_path))
            backup = raw.with_name(raw.stem + ".raw" + raw.suffix)
            raw.replace(backup)
            try:
                shutil.move(str(result.output_path), str(raw))
            except Exception:
                backup.replace(raw)
                raise
            backup.unlink(missing_ok=True)
            asset.media_manifest["video_use_manual_edit"] = {
                "edl_entries": len(result.edl),
                "self_eval_score": result.self_eval_score,
                "issues": result.issues[:5],
            }
            self._app.store.save_asset(asset)
            return {"asset_id": asset_id, "status": "edited",
                    "edl_entries": len(result.edl),
                    "self_eval_score": result.self_eval_score,
                    "issues": result.issues}
        except Exception as exc:
            return {"error": str(exc)}


class CockpitHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for Cockpit web UI."""

    app: BlueWavesApplication
    cockpit: CockpitApp

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/dashboard":
            self.serve_dashboard()
        elif path == "/api/dashboard":
            self.serve_json(self.cockpit.get_dashboard_data())
        elif path == "/api/approvals":
            self.serve_json(self.cockpit.get_pending_approvals())
        elif path == "/api/queue":
            self.serve_json(self.cockpit.get_queue())
        elif path == "/api/health":
            self.serve_json(self.app.health())
        elif path == "/api/finance":
            self.serve_json(self.app.get_finance_status())
        elif path == "/feed/rss.xml":
            self.serve_rss(self.cockpit.get_rss_feed())
        elif path == "/api/providers":
            self.serve_json(self.cockpit.get_provider_catalog())
        elif path == "/api/metrics":
            self.serve_json(self.cockpit.get_metrics())
        elif path == "/api/monetization/mediakit":
            self.serve_json(self.cockpit.get_media_kit())
        elif path == "/api/sponsors":
            self.serve_json(self.cockpit.get_sponsors())
        elif path == "/api/crew":
            self.serve_json(self.cockpit.get_crew())
        elif path == "/api/library":
            self.serve_json(self.cockpit.get_library())
        elif path == "/api/intelligence":
            self.serve_json(self.cockpit.get_intelligence())
        elif path == "/api/finance/plan":
            self.serve_json(self.cockpit.get_finance_plan())
        elif path == "/api/shepo/finance":
            self.serve_json(self.cockpit.get_finance_plan())
        elif path == "/api/shepo/projections":
            plan = self.cockpit.get_finance_plan()
            shepo = plan.get("shepo_report", {})
            self.serve_json({
                "revenue_projection": shepo.get("revenue_projection", {}),
                "break_even_analysis": shepo.get("break_even_analysis", {}),
            })
        elif path == "/api/scheduler":
            self.serve_json(self.cockpit.get_scheduler())
        elif path == "/api/connections":
            self.serve_json(self.cockpit.get_connections())
        elif path == "/api/languages":
            self.serve_json({"languages": supported_languages()})
        elif path.startswith("/api/quality/"):
            parts = path.split("/")
            if len(parts) >= 4 and parts[3]:
                self.serve_json(self.cockpit.get_quality_breakdown(parts[3]))
            else:
                self.send_error(400)
        elif path == "/api/video-use/status":
            self.serve_json(self.cockpit.get_video_use_status())
        elif path.startswith("/media/"):
            self.serve_media(path)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        print(f"[DEBUG] POST: path={path}, content_length={content_length}")
        body = self.rfile.read(content_length) if content_length > 0 else b''
        print(f"[DEBUG] POST: body_len={len(body)}, body[:100]={body[:100]}")

        if path.startswith("/api/approve/"):
            parts = path.split("/")
            if len(parts) >= 5:
                content_type = parts[3]
                asset_id = parts[4]
                result = self.cockpit.approve_content(content_type, asset_id)
                self.serve_json(result)
            else:
                self.send_error(400)
        elif path == "/api/request":
            try:
                data = json.loads(body) if body else {}
                result = self.cockpit.add_request(
                    data.get("content_type", "video"),
                    data.get("topic", ""),
                    data.get("priority", "normal"),
                    data.get("quality", "high"),
                )
                self.serve_json(result)
            except json.JSONDecodeError:
                self.send_error(400)
        elif path.startswith("/api/providers/approve/"):
            parts = path.split("/")
            if len(parts) >= 5:
                provider = parts[4]
                actor = json.loads(body).get("actor", "owner") if body else "owner"
                self.serve_json(self.cockpit.approve_provider(provider, actor))
            else:
                self.send_error(400)
        elif path.startswith("/api/providers/revoke/"):
            parts = path.split("/")
            if len(parts) >= 5:
                provider = parts[4]
                self.serve_json(self.cockpit.revoke_provider(provider))
            else:
                self.send_error(400)
        elif path == "/api/analytics/sync":
            self.serve_json(self.cockpit.sync_analytics())
        elif path == "/api/scheduler/tick":
            self.serve_json(self.cockpit.run_scheduler())
        elif path == "/api/sponsors":
            try:
                data = json.loads(body) if body else {}
                self.serve_json(self.cockpit.upsert_sponsor(data))
            except json.JSONDecodeError:
                self.send_error(400)
        elif path.startswith("/api/sponsors/"):
            parts = path.split("/")
            if len(parts) >= 5 and parts[4] == "email":
                prospect_id = parts[3]
                company = json.loads(body).get("company", "") if body else ""
                self.serve_json(self.cockpit.sponsor_email(prospect_id, company))
            else:
                self.send_error(400)
        elif path.startswith("/api/reject/"):
            parts = path.split("/")
            if len(parts) >= 5:
                reason = json.loads(body).get("reason", "owner rejected") if body else "owner rejected"
                self.serve_json(self.cockpit.reject_media(parts[3], parts[4], reason))
            else:
                self.send_error(400)
        elif path.startswith("/api/retry/"):
            parts = path.split("/")
            if len(parts) >= 5:
                data = json.loads(body) if body else {}
                self.serve_json(self.cockpit.retry_media(parts[3], parts[4],
                                                          data.get("enhancement", "Improve quality and clarity."),
                                                          data.get("quality", "high")))
            else:
                self.send_error(400)
        elif path.startswith("/api/publish/"):
            parts = path.split("/")
            if len(parts) >= 5:
                data = json.loads(body) if body else {}
                self.serve_json(self.cockpit.publish_media(parts[3], parts[4], data.get("channel", "youtube")))
            else:
                self.send_error(400)
        elif path == "/api/memory/approve":
            try:
                data = json.loads(body) if body else {}
                self.serve_json(self.cockpit.approve_recommendation(data.get("memory_id", "")))
            except json.JSONDecodeError:
                self.send_error(400)
        elif path == "/api/connections":
            try:
                data = json.loads(body) if body else {}
                provider = data.pop("provider", "")
                result = self.cockpit.save_connection(provider, data)
                self.serve_json(result)
            except json.JSONDecodeError:
                self.send_error(400)
        elif path.startswith("/api/generate/"):
            parts = path.split("/")
            if len(parts) >= 4:
                content_type = parts[3]
                try:
                    raw_body = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else (body if isinstance(body, str) else "{}")
                    print(f"[DEBUG] generate: content_type={content_type}, raw_body={raw_body[:500]}")
                    data = json.loads(raw_body)
                    if not isinstance(data, dict):
                        raise TypeError("JSON body must be an object")
                    self.serve_json(self.cockpit.generate_media(content_type, data))
                except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                    print(f"[DEBUG] generate error: {exc}, raw_body={raw_body[:500]}")
                    self.send_error(400)
            else:
                self.send_error(400)
        elif path.startswith("/api/video-use/edit/"):
            parts = path.split("/")
            if len(parts) >= 5 and parts[4]:
                self.serve_json(self.cockpit.trigger_video_use_edit(parts[4]))
            else:
                self.send_error(400)
        else:
            self.send_error(404)

    def serve_dashboard(self) -> None:
        html = self.get_dashboard_html()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_json(self, data: Any) -> None:
        json_data = json.dumps(data, indent=2)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json_data.encode())

    def serve_rss(self, xml: str) -> None:
        self.send_response(200)
        self.send_header('Content-Type', 'application/rss+xml; charset=utf-8')
        self.end_headers()
        self.wfile.write(xml.encode("utf-8"))

    def serve_media(self, path: str) -> None:
        parts = path.split("/")
        if len(parts) != 4:
            self.send_error(404)
            return
        _, _, content_type, asset_id = parts
        raw_path = self.cockpit.get_media_path(content_type, asset_id)
        if not raw_path:
            self._json_err(404, {"error": "media_not_found"})
            return
        media = Path(str(raw_path))
        if not media.exists() or media.stat().st_size == 0:
            self._json_err(404, {"error": "media_not_found"})
            return
        mime = "video/mp4" if content_type == "video" else "audio/wav"
        try:
            body = media.read_bytes()
        except OSError:
            self._json_err(500, {"error": "media_read_failed"})
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_err(self, status: int, data: Any) -> None:
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def get_dashboard_html(self) -> str:
        """Return the comprehensive single-page Cockpit dashboard."""
        return DASHBOARD_HTML

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging."""
        pass


def start_cockpit(app: BlueWavesApplication, host: str = "0.0.0.0", port: int = 8420) -> None:
    """Start the Cockpit web server."""
    cockpit = CockpitApp(app)
    CockpitHTTPHandler.app = app
    CockpitHTTPHandler.cockpit = cockpit

    server = HTTPServer((host, port), CockpitHTTPHandler)
    print(f"Blue Waves Cockpit v0.3.0")
    print(f"Starting server on http://{host}:{port}")
    print(f"Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
