from __future__ import annotations
import json
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from typing import Any

from .agents import roster
from .application import BlueWavesApplication


class BlueWavesHandler(BaseHTTPRequestHandler):
    application: BlueWavesApplication

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _asset(self, path: str):
        asset_id = path.removeprefix("/v1/assets/").split("/", 1)[0]
        return self.application.get_asset(asset_id)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        # ── Original v0.1.0 endpoints ──
        if path == "/health":
            self._json(200, self.application.health())
        elif path == "/v1/agents":
            self._json(200, {"tenant_id": self.application.settings.tenant_id, "agents": roster()})
        elif path == "/v1/review":
            self._json(200, self.application.weekly_review())
        # ── New v0.2.0 endpoints ──
        elif path == "/v1/queue":
            self._json(200, self.application.get_queue_status())
        elif path == "/v1/queue/list":
            self._json(200, {"requests": [r.to_dict() for r in self.application.queue.get_all()]})
        elif path == "/v1/finance":
            self._json(200, self.application.get_finance_status())
        elif path == "/v1/providers/health":
            self._json(200, self.application.get_health_status())
        elif path == "/v1/providers/catalog":
            self._json(200, {"providers": self.application.provider_registry.catalog()})
        elif path == "/v1/music":
            self._json(200, {"assets": [a.to_dict() for a in self.application.music_assets.values() if self._media_exists(a.audio_path)]})
        elif path == "/v1/podcasts":
            self._json(200, {"assets": [a.to_dict() for a in self.application.podcast_assets.values() if self._media_exists(a.audio_path)]})
        elif path == "/v1/videos":
            self._json(200, {"assets": [a.to_dict() for a in self.application.assets.values()
                                          if self._media_exists(a.media_manifest.get("video_path"))]})
        elif path == "/v1/approvals":
            pending = []
            ready = []
            for aid, a in self.application.music_assets.items():
                if a.status.value == "awaiting_owner":
                    pending.append({"type": "music", "asset_id": aid, "title": a.title, "status": a.status.value, "media_url": f"/media/music/{aid}"})
                elif a.status.value == "approved":
                    ready.append({"type": "music", "asset_id": aid, "title": a.title})
            for aid, a in self.application.podcast_assets.items():
                if a.status.value == "awaiting_owner":
                    pending.append({"type": "podcast", "asset_id": aid, "title": a.title, "status": a.status.value, "media_url": f"/media/podcast/{aid}"})
                elif a.status.value == "approved":
                    ready.append({"type": "podcast", "asset_id": aid, "title": a.title})
            for aid, a in self.application.assets.items():
                if a.status.value == "awaiting_owner":
                    pending.append({"type": "video", "asset_id": aid, "title": a.topic, "status": a.status.value, "media_url": f"/media/video/{aid}"})
                elif a.status.value == "approved":
                    ready.append({"type": "video", "asset_id": aid, "title": a.topic})
            retryable = []
            for kind, assets in (("music", self.application.music_assets), ("podcast", self.application.podcast_assets), ("video", self.application.assets)):
                for aid, a in assets.items():
                    if a.status.value == "rejected":
                        retryable.append({"type": kind, "asset_id": aid, "title": getattr(a, "title", getattr(a, "topic", aid)), "status": "rejected", "reason": a.rejection_reason})
            self._json(200, {"pending": pending, "retryable": retryable, "ready_to_publish": ready})
        elif path == "/v1/connections":
            self._json(200, self.application.connection_status())
        elif path == "/v1/intelligence":
            self._json(200, self.application.intelligence())
        elif path.startswith("/media/"):
            self._serve_media(path)
        elif path == "/oauth/youtube/callback":
            query = parse_qs(parsed.query)
            try:
                result = self.application.youtube_oauth_callback(query.get("code", [""])[0], query.get("state", [""])[0])
                self._json(200, result)
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": f"OAuth callback failed: {e}"})
        elif path == "/":
                secret = self.headers.get("X-Cockpit-Secret-Key")
                if not secret or secret != "secret123":
                    self._json(401, {"error": "unauthorized"})
                    return
                self._serve_dashboard()
                return
        else:
            self._json(404, {"error": "not_found"})

    @staticmethod
    def _media_exists(raw_path: str | None) -> bool:
        if not raw_path:
            return False
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def _serve_media(self, path: str) -> None:
        parts = path.split("/")
        if len(parts) != 4:
            self._json(404, {"error": "media_not_found"})
            return
        content_type, asset_id = parts[2], parts[3]
        asset = (self.application.music_assets.get(asset_id) if content_type == "music" else
                 self.application.podcast_assets.get(asset_id) if content_type == "podcast" else
                 self.application.assets.get(asset_id) if content_type == "video" else None)
        if not asset:
            self._json(404, {"error": "media_not_found"})
            return
        raw_path = asset.audio_path if content_type in ("music", "podcast") else asset.media_manifest.get("video_path")
        if not raw_path:
            self._json(404, {"error": "media_not_found"})
            return
        file_path = Path(raw_path)
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        try:
            resolved = file_path.resolve()
            if not resolved.is_file() or resolved.stat().st_size == 0:
                raise FileNotFoundError
            body = resolved.read_bytes()
        except (OSError, FileNotFoundError):
            self._json(404, {"error": "media_file_not_found"})
            return
        mime = "video/mp4" if content_type == "video" else "audio/wav"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            body = self._body()
            # ── Original v0.1.0 endpoints ──
            if path == "/v1/register":
                self._json(200, self.application.register())
                return
            if path == "/v1/lessons":
                ar, en = self.application.create_bilingual_lesson(
                    topic=str(body["topic"]),
                    source_url=body.get("source_url"),
                    source_verified=bool(body.get("source_verified", False)),
                    lesson_id=body.get("lesson_id"),
                )
                self._json(201, {"assets": [ar.to_dict(), en.to_dict()]})
                return
            if path.endswith("/produce") and path.startswith("/v1/assets/"):
                asset = self._asset(path)
                self._json(200, self.application.fact_check_and_produce(asset))
                return
            if path.endswith("/approve") and path.startswith("/v1/assets/"):
                asset = self._asset(path)
                result = self.application.owner_approve(asset, reason=str(body.get("reason", "owner reviewed preview")), approver=body.get("approver"))
                self._json(200, result)
                return
            if path.endswith("/publish") and path.startswith("/v1/assets/"):
                asset = self._asset(path)
                result = self.application.publish(asset, str(body["channel"]), int(body.get("weekly_count", 0)))
                self._json(200, result)
                return
            if path.endswith("/metrics") and path.startswith("/v1/assets/"):
                asset = self._asset(path)
                result = self.application.record_metric(asset, str(body["channel"]), str(body["metric"]), float(body["value"]), str(body.get("source", "owner_import")))
                self._json(201, result)
                return
            # ── New v0.2.0 endpoints ──
            if path == "/v1/request":
                request = self.application.add_content_request(
                    content_type=str(body["content_type"]),
                    topic=str(body["topic"]),
                    priority=str(body.get("priority", "normal")),
                    quality=str(body.get("quality", "high")),
                    language=str(body.get("language", "en")),
                )
                self._json(201, request.to_dict())
                return
            if path == "/v1/generate/music":
                asset = self.application.generate_music(
                    topic=str(body["topic"]),
                    genre=str(body.get("genre", "cinematic")),
                    mood=str(body.get("mood", "inspirational")),
                    duration_seconds=int(body.get("duration_seconds", 180)),
                    quality=str(body.get("quality", "high")),
                )
                self._json(201, asset.to_dict() if asset else {"error": "generation failed"})
                return
            if path == "/v1/generate/podcast":
                asset = self.application.generate_podcast(
                    topic=str(body["topic"]),
                    script=str(body["script"]),
                    host_voice=str(body.get("host_voice", "en-US-AriaNeural")),
                    guest_voice=str(body["guest_voice"]) if body.get("guest_voice") else None,
                    duration_seconds=int(body.get("duration_seconds", 1800)),
                    format=str(body.get("format", "dialogue")),
                    quality=str(body.get("quality", "high")),
                )
                self._json(201, asset.to_dict() if asset else {"error": "generation failed"})
                return
            if path == "/v1/generate/video":
                asset = self.application.generate_video(
                    topic=str(body["topic"]),
                    prompt=str(body["prompt"]),
                    duration=int(body.get("duration", 5)),
                    quality=str(body.get("quality", "high")),
                )
                self._json(201, asset.to_dict() if asset else {"error": "generation failed"})
                return
            if path.startswith("/v1/approve/music/"):
                asset_id = path.removeprefix("/v1/approve/music/")
                result = self.application.approve_music(asset_id)
                self._json(200, result)
                return
            if path.startswith("/v1/approve/podcast/"):
                asset_id = path.removeprefix("/v1/approve/podcast/")
                result = self.application.approve_podcast(asset_id)
                self._json(200, result)
                return
            if path.startswith("/v1/publish/music/"):
                asset_id = path.removeprefix("/v1/publish/music/")
                channel = str(body.get("channel", "youtube"))
                result = self.application.publish_music(asset_id, channel)
                self._json(200, result)
                return
            if path.startswith("/v1/publish/podcast/"):
                asset_id = path.removeprefix("/v1/publish/podcast/")
                channel = str(body.get("channel", "youtube"))
                result = self.application.publish_podcast(asset_id, channel)
                self._json(200, result)
                return
            if path.startswith("/v1/reject/music/"):
                self._json(200, self.application.reject_music(path.removeprefix("/v1/reject/music/"), str(body.get("reason", "owner rejected")), body.get("approver")))
                return
            if path.startswith("/v1/reject/podcast/"):
                self._json(200, self.application.reject_podcast(path.removeprefix("/v1/reject/podcast/"), str(body.get("reason", "owner rejected")), body.get("approver")))
                return
            if path.startswith("/v1/reject/video/"):
                self._json(200, self.application.reject_asset(self.application.get_asset(path.removeprefix("/v1/reject/video/")), str(body.get("reason", "owner rejected")), body.get("approver")))
                return
            if path.startswith("/v1/retry/music/"):
                asset = self.application.retry_music(path.removeprefix("/v1/retry/music/"), str(body.get("enhancement", "Improve arrangement, dynamics, and clarity.")), str(body.get("quality", "high")), body.get("approver"))
                self._json(201, asset.to_dict())
                return
            if path.startswith("/v1/retry/podcast/"):
                asset = self.application.retry_podcast(path.removeprefix("/v1/retry/podcast/"), str(body.get("enhancement", "Improve pacing, diction, and mix balance.")), str(body.get("quality", "high")), body.get("approver"))
                self._json(201, asset.to_dict())
                return
            if path.startswith("/v1/retry/video/"):
                asset = self.application.retry_video(path.removeprefix("/v1/retry/video/"), str(body.get("enhancement", "Improve visual pacing, composition, and readability.")), str(body.get("quality", "high")), body.get("approver"))
                self._json(201, asset.to_dict())
                return
            if path == "/v1/connections":
                provider = str(body.pop("provider"))
                self._json(200, self.application.save_connection(provider, body))
                return
            if path == "/v1/connections/youtube/oauth/start":
                self._json(200, {"authorization_url": self.application.youtube_oauth_start(str(body["redirect_uri"]))})
                return
            if path == "/v1/memory/approve":
                self._json(200, self.application.approve_memory(str(body["memory_id"])))
                return
            if path.startswith("/v1/metrics/"):
                parts = path.split("/")
                if len(parts) != 4: raise ValueError("metric path must include an asset id")
                self._json(201, self.application.record_media_metric(parts[3], str(body["channel"]), str(body["metric"]), float(body["value"]), str(body.get("source", "owner_import"))))
                return
            self._json(404, {"error": "not_found"})
        except (KeyError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # API boundary must return JSON, not an HTML traceback.
            self._json(500, {"error": str(exc)})

    def _serve_dashboard(self) -> None:
        html = self._get_cockpit_html()
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_cockpit_html(self) -> str:
        return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Blue Waves Cockpit v0.2.0</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#e0e0e0}
.container{max-width:1400px;margin:0 auto;padding:20px}
h1{color:#4fc3f7;margin-bottom:5px}
.subtitle{color:#666;margin-bottom:20px;font-size:0.9em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:16px}
.card{background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:16px}
.card h2{color:#81c784;margin-bottom:12px;font-size:1.1em;border-bottom:1px solid #333;padding-bottom:8px}
.card h3{color:#ffb74d;margin:10px 0 6px;font-size:0.95em}
.stat{display:flex;justify-content:space-between;margin:4px 0;font-size:0.9em}
.stat-label{color:#999}
.stat-value{color:#fff;font-weight:bold}
.agent{background:#222;padding:10px;border-radius:4px;margin:6px 0;border-left:3px solid #4fc3f7}
.agent-name{color:#4fc3f7;font-weight:bold}
.agent-role{color:#999;font-size:0.85em}
.agent-can{color:#81c784;font-size:0.8em;margin-top:4px}
.agent-cannot{color:#ef5350;font-size:0.8em}
.btn{background:#4fc3f7;color:#000;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;margin:2px;font-size:0.85em}
.btn:hover{background:#81d4fa}
.btn-green{background:#66bb6a;color:#fff}
.btn-green:hover{background:#81c784}
.btn-orange{background:#ffa726;color:#000}
.btn-orange:hover{background:#ffb74d}
.btn-red{background:#ef5350;color:#fff}
.btn-red:hover{background:#f44336}
.form-group{margin:8px 0}
.form-group label{display:block;color:#999;margin-bottom:4px;font-size:0.85em}
.form-group input,.form-group select,.form-group textarea{width:100%;padding:6px;background:#333;border:1px solid #555;color:#fff;border-radius:4px;font-size:0.85em}
.form-group textarea{min-height:60px;resize:vertical}
#status{padding:10px;background:#111;border-radius:4px;margin-top:16px;font-size:0.85em;border:1px solid #333}
.section-title{color:#4fc3f7;font-size:1em;margin:16px 0 8px;padding-bottom:4px;border-bottom:1px solid #222}
table{width:100%;border-collapse:collapse;font-size:0.85em}
audio,video{width:100%;margin-top:10px;border-radius:4px}
th,td{padding:6px 8px;text-align:left;border-bottom:1px solid #333}
th{color:#81c784;font-weight:bold}
tr:hover{background:#222}
</style>
</head>
<body>
<div class="container">
<h1>Blue Waves Cockpit v0.2.0</h1>
<p class="subtitle">Multi-Format Content Studio &mdash; Two-Gate Governance Model</p>

<div class="grid">
<!-- SYSTEM HEALTH -->
<div class="card">
<h2>System Health</h2>
<div id="health">Loading...</div>
</div>

<!-- QUEUE STATUS -->
<div class="card">
<h2>Content Queue</h2>
<div id="queue">Loading...</div>
</div>

<!-- FINANCE -->
<div class="card">
<h2>Finance (SHIPO)</h2>
<div id="finance">Loading...</div>
</div>

<!-- PROVIDER HEALTH -->
<div class="card">
<h2>Provider Health</h2>
<div id="providers">Loading...</div>
</div>
</div>

<!-- CREW MEMBERS -->
<div class="section-title">Crew Members</div>
<div id="agents">Loading...</div>

<!-- CONTENT LIBRARY -->
<div class="section-title">Generated Content Library</div>
<div id="library" class="grid"><p style="color:#666">Loading generated media...</p></div>

<!-- PENDING APPROVALS -->
<div class="section-title">Pending Approvals (Gate 2)</div>
<div id="approvals">Loading...</div>

<!-- CONTENT ACTIONS -->
<div class="section-title">Content Generation & Actions</div>
<div class="grid">
<div class="card">
<h2>Generate Music</h2>
<div class="form-group"><label>Topic</label><input id="music-topic" placeholder="e.g. Ocean waves"></div>
<div class="form-group"><label>Genre</label><select id="music-genre"><option>pop</option><option>cinematic</option><option>ambient</option><option>rock</option><option>jazz</option><option>electronic</option><option>lofi</option></select></div>
<div class="form-group"><label>Mood</label><select id="music-mood"><option>happy</option><option>inspirational</option><option>calm</option><option>energetic</option><option>dramatic</option></select></div>
<div class="form-group"><label>Duration (sec)</label><input id="music-duration" type="number" value="60"></div>
<button class="btn btn-green" onclick="generateMusic()">Generate Music</button>
</div>

<div class="card">
<h2>Generate Podcast</h2>
<div class="form-group"><label>Topic</label><input id="pod-topic" placeholder="e.g. Software engineering"></div>
<div class="form-group"><label>Script</label><textarea id="pod-script" placeholder="Enter podcast script..."></textarea></div>
<div class="form-group"><label>Host Voice</label><select id="pod-host"><option value="en-GB-SoniaNeural">UK Female (Sonia)</option><option value="en-GB-RyanNeural">UK Male (Ryan)</option><option value="en-US-AriaNeural">US Female (Aria)</option><option value="en-US-GuyNeural">US Male (Guy)</option></select></div>
<div class="form-group"><label>Guest Voice (dialogue)</label><select id="pod-guest"><option value="en-US-GuyNeural">US Male (Guy)</option><option value="en-GB-RyanNeural">UK Male (Ryan)</option><option value="">No guest</option></select></div>
<div class="form-group"><label>Format</label><select id="pod-format"><option value="dialogue">Two voices / dialogue</option><option value="solo">Solo</option></select></div>
<div class="form-group"><label>Duration (sec)</label><input id="pod-duration" type="number" value="600"></div>
<button class="btn btn-green" onclick="generatePodcast()">Generate Podcast</button>
</div>

<div class="card">
<h2>Generate Video</h2>
<div class="form-group"><label>Topic</label><input id="vid-topic" placeholder="e.g. AI basics"></div>
<div class="form-group"><label>Prompt</label><textarea id="vid-prompt" placeholder="Describe the video..."></textarea></div>
<div class="form-group"><label>Duration (sec)</label><input id="vid-duration" type="number" value="10"></div>
<div class="form-group"><label>Quality</label><select id="vid-quality"><option>high</option><option>standard</option><option>draft</option></select></div>
<button class="btn btn-green" onclick="generateVideo()">Generate Video</button>
</div>

<div class="card">
<h2>Add Queue Request</h2>
<div class="form-group"><label>Content Type</label><select id="req-type"><option>video</option><option>music</option><option>podcast</option></select></div>
<div class="form-group"><label>Topic</label><input id="req-topic" placeholder="Enter topic..."></div>
<div class="form-group"><label>Priority</label><select id="req-priority"><option>normal</option><option>high</option><option>low</option></select></div>
<div class="form-group"><label>Quality</label><select id="req-quality"><option>high</option><option>standard</option><option>free</option></select></div>
<button class="btn" onclick="addRequest()">Add to Queue</button>
</div>
</div>

<!-- OWNER CONTROL PLANE -->
<div class="section-title">Owner Control Plane</div>
<div class="grid">
<div class="card"><h2>Connections & API Keys</h2>
<p style="color:#999;font-size:.8em">Secrets are stored locally and never displayed back. YouTube requires Google OAuth client credentials; Suno uses its platform API key/token (consumer-plan login is not a documented OAuth integration).</p>
<div class="form-group"><label>OpenRouter API key</label><input id="key-openrouter" type="password"></div>
<div class="form-group"><label>Groq API key</label><input id="key-groq" type="password"></div>
<div class="form-group"><label>NVIDIA NIM API key</label><input id="key-nvidia" type="password"></div>
<div class="form-group"><label>Cerebras API key</label><input id="key-cerebras" type="password"></div>
<div class="form-group"><label>Hugging Face token</label><input id="key-huggingface" type="password"></div>
<div class="form-group"><label>aimlapi API key</label><input id="key-aimlapi" type="password"></div>
<div class="form-group"><label>KAI.AI API key</label><input id="key-kai" type="password"></div>
<div class="form-group"><label>Google OAuth client ID</label><input id="yt-client-id"></div>
<div class="form-group"><label>Google OAuth client secret</label><input id="yt-client-secret" type="password"></div>
<button class="btn btn-orange" onclick="saveConnections()">Save connections</button>
<button class="btn" onclick="startYouTubeOAuth()">Connect YouTube via OAuth</button><div id="connections"></div>
<div class="card"><h2>SHIPO + KOYOSHU Intelligence</h2><p style="color:#999;font-size:.8em">Import audience metrics, inspect winners, then explicitly approve any memory before it influences future production.</p>
<div class="form-group"><label>Asset ID</label><input id="metric-asset"></div><div class="form-group"><label>Metric (views, likes, comments, watch_time)</label><input id="metric-name"></div><div class="form-group"><label>Value</label><input id="metric-value" type="number" step="any"></div><button class="btn" onclick="recordMetric()">Import metric</button><button class="btn" onclick="loadIntelligence()">Refresh analysis</button><div id="intelligence">Not loaded</div></div>
</div>

<!-- LEGACY ACTIONS -->
<div class="section-title">Legacy Actions (v0.1.0)</div>
<div class="grid">
<div class="card">
<h2>Bilingual Lesson</h2>
<div class="form-group"><label>Topic</label><input id="lesson-topic" placeholder="Enter topic..."></div>
<div class="form-group"><label>Source URL (optional)</label><input id="lesson-source" placeholder="https://..."></div>
<button class="btn" onclick="createLesson()">Create Lesson</button>
</div>
<div class="card">
<h2>Register with Codex</h2>
<button class="btn" onclick="register()">Register</button>
</div>
<div class="card">
<h2>Weekly Review</h2>
<button class="btn" onclick="review()">Run Review</button>
</div>
</div>

<div id="status"></div>
</div>

<script>
const api = (path, opts) => fetch(path, opts).then(r => r.json());

async function loadAll() {
  try {
    const [health, queue, finance, providers, agents, approvals, music, podcasts, videos] = await Promise.all([
      api('/health'), api('/v1/queue'), api('/v1/finance'),
      api('/v1/providers/health'), api('/v1/agents'), api('/v1/approvals'),
      api('/v1/music'), api('/v1/podcasts'), api('/v1/videos')
    ]);

    document.getElementById('health').innerHTML = `
      <div class="stat"><span class="stat-label">Version:</span><span class="stat-value">${health.version}</span></div>
      <div class="stat"><span class="stat-label">Tenant:</span><span class="stat-value">${health.tenant_id}</span></div>
      <div class="stat"><span class="stat-label">Ledger:</span><span class="stat-value">${health.ledger_intact ? 'Intact' : 'BROKEN'}</span></div>
      <div class="stat"><span class="stat-label">Cloud Budget:</span><span class="stat-value">$${(health.cloud_budget_cents/100).toFixed(2)}/mo</span></div>
      <div class="stat"><span class="stat-label">Motion Route:</span><span class="stat-value">${health.hybrid_motion_route}</span></div>`;

    document.getElementById('queue').innerHTML = `
      <div class="stat"><span class="stat-label">Total:</span><span class="stat-value">${queue.total}</span></div>
      <div class="stat"><span class="stat-label">Pending:</span><span class="stat-value">${queue.pending}</span></div>
      <div class="stat"><span class="stat-label">Ready:</span><span class="stat-value">${queue.ready_to_publish}</span></div>
      <div class="stat"><span class="stat-label">Published:</span><span class="stat-value">${queue.published}</span></div>
      <div class="stat"><span class="stat-label">Rejected:</span><span class="stat-value">${queue.rejected}</span></div>`;

    document.getElementById('finance').innerHTML = `
      <div class="stat"><span class="stat-label">Weekly:</span><span class="stat-value">$${(finance.weekly_costs/100).toFixed(2)}</span></div>
      <div class="stat"><span class="stat-label">Music:</span><span class="stat-value">$${(finance.music_costs/100).toFixed(2)}</span></div>
      <div class="stat"><span class="stat-label">Podcast:</span><span class="stat-value">$${(finance.podcast_costs/100).toFixed(2)}</span></div>
      <div class="stat"><span class="stat-label">Video:</span><span class="stat-value">$${(finance.video_costs/100).toFixed(2)}</span></div>`;

    let ph = '';
    for (const [name, info] of Object.entries(providers)) {
      ph += '<div class="stat"><span class="stat-label">'+name+':</span><span class="stat-value">'+info.status+'</span></div>';
    }
    document.getElementById('providers').innerHTML = ph || '<div class="stat"><span class="stat-label">No providers registered</span></div>';

    const library = [...music.assets.map(a=>({...a, type:'music', media:a.audio_path})), ...podcasts.assets.map(a=>({...a, type:'podcast', media:a.audio_path})), ...videos.assets.map(a=>({...a, type:'video', media:a.media_manifest.video_path}))];
    document.getElementById('library').innerHTML = library.length ? library.map(a => {
      const src='/media/'+a.type+'/'+a.asset_id;
      const player=a.type==='video' ? `<video controls preload="metadata" src="${src}"></video>` : `<audio controls preload="metadata" src="${src}"></audio>`;
      return `<div class="card"><h2>${a.title || a.topic}</h2><div class="stat"><span class="stat-label">Type:</span><span class="stat-value">${a.type}</span></div><div class="stat"><span class="stat-label">Status:</span><span class="stat-value">${a.status}</span></div>${player}<p style="color:#777;font-size:.75em">${a.asset_id}</p></div>`;
    }).join('') : '<p style="color:#666">No generated content yet.</p>';

    let ah = '';
    for (const a of agents.agents) {
      ah += `<div class="agent">
        <div class="agent-name">${a.name} (${a.id})</div>
        <div class="agent-role">${a.role} &mdash; Tier: ${a.tier}</div>
        <div class="agent-can">Can: ${a.can.join(', ')}</div>
        <div class="agent-cannot">Cannot: ${a.cannot.join(', ')}</div>
      </div>`;
    }
    document.getElementById('agents').innerHTML = ah;

    let ap = '<table><tr><th>Type</th><th>Asset ID</th><th>Title / Preview</th><th>Owner action</th></tr>';
    for (const a of approvals.pending || []) {
      const preview = a.type==='video' ? `<video controls preload="metadata" src="${a.media_url}"></video>` : `<audio controls preload="metadata" src="${a.media_url}"></audio>`;
      ap += `<tr><td>${a.type}</td><td>${a.asset_id}</td><td>${a.title}<br>${preview}</td>
        <td><button class="btn btn-green" onclick="approveItem('${a.type}','${a.asset_id}')">Approve</button>
        <button class="btn btn-red" onclick="rejectItem('${a.type}','${a.asset_id}')">Reject</button></td></tr>`;
    }
    for (const a of approvals.retryable || []) {
      ap += `<tr><td>${a.type}</td><td>${a.asset_id}</td><td>${a.title}<br><small>Rejected: ${a.reason || 'owner feedback required'}</small></td>
        <td><input id="enh-${a.asset_id}" placeholder="Enhancement" value="Improve quality and clarity."><button class="btn btn-orange" onclick="retryItem('${a.type}','${a.asset_id}')">Generate another attempt</button></td></tr>`;
    }
    for (const a of approvals.ready_to_publish || []) {
      ap += `<tr><td>${a.type}</td><td>${a.asset_id}</td><td>${a.title}<br><small>Approved; ready to publish</small></td>
        <td><button class="btn btn-green" onclick="publishItem('${a.type}','${a.asset_id}')">Publish to YouTube</button></td></tr>`;
    }
    ap += '</table>';
    document.getElementById('approvals').innerHTML = (approvals.pending?.length || approvals.retryable?.length || approvals.ready_to_publish?.length) ? ap : '<p style="color:#666">No pending approvals</p>';
  } catch(e) { console.error(e); }
}

function status(msg) { document.getElementById('status').innerHTML = '<pre>'+msg+'</pre>'; }

async function generateMusic() {
  const r = await api('/v1/generate/music', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({topic:document.getElementById('music-topic').value, genre:document.getElementById('music-genre').value,
      mood:document.getElementById('music-mood').value, duration_seconds:parseInt(document.getElementById('music-duration').value)})});
  status(JSON.stringify(r,null,2)); loadAll();
}

async function rejectItem(type, id) {
  const r = await api('/v1/reject/'+type+'/'+id, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({reason:'Owner rejected in Cockpit'})});
  status(JSON.stringify(r,null,2)); loadAll();
}
async function retryItem(type, id) {
  const enhancement=document.getElementById('enh-'+id).value;
  const r=await api('/v1/retry/'+type+'/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enhancement,quality:'high'})});
  status(JSON.stringify(r,null,2)); loadAll();
}
async function publishItem(type, id) {
  const path=type==='video' ? '/v1/assets/'+id+'/publish' : '/v1/publish/'+type+'/'+id;
  const r=await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel:'youtube'})});
  status(JSON.stringify(r,null,2)); loadAll();
}
async function saveConnections() {
  const values=[['openrouter','api_key','key-openrouter'],['groq','api_key','key-groq'],['nvidia_nim','api_key','key-nvidia'],['cerebras','api_key','key-cerebras'],['huggingface','api_key','key-huggingface'],['aimlapi','api_key','key-aimlapi'],['kai','api_key','key-kai']];
  for (const [provider,key,id] of values) { const value=document.getElementById(id).value; if(value) await api('/v1/connections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider,[key]:value})}); }
  const client_id=document.getElementById('yt-client-id').value, client_secret=document.getElementById('yt-client-secret').value;
  if(client_id) await api('/v1/connections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:'youtube',client_id,client_secret})});
  status('Connections saved.'); loadConnections();
}
async function loadConnections() { const c=await api('/v1/connections'); document.getElementById('connections').innerText=JSON.stringify(c,null,2); }
async function startYouTubeOAuth() { const r=await api('/v1/connections/youtube/oauth/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({redirect_uri:location.origin+'/oauth/youtube/callback'})}); if(r.authorization_url) location.href=r.authorization_url; else status(JSON.stringify(r)); }
async function loadIntelligence() { const r=await api('/v1/intelligence'); document.getElementById('intelligence').innerHTML='<pre>'+JSON.stringify(r,null,2)+'</pre>'; }
async function recordMetric() { const id=document.getElementById('metric-asset').value; const r=await api('/v1/metrics/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel:'youtube',metric:document.getElementById('metric-name').value,value:parseFloat(document.getElementById('metric-value').value)})}); status(JSON.stringify(r,null,2)); loadIntelligence(); }

async function generatePodcast() {
  const r = await api('/v1/generate/podcast', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({topic:document.getElementById('pod-topic').value, script:document.getElementById('pod-script').value,
      host_voice:document.getElementById('pod-host').value, guest_voice:document.getElementById('pod-guest').value || null,
      format:document.getElementById('pod-format').value, duration_seconds:parseInt(document.getElementById('pod-duration').value)})});
  status(JSON.stringify(r,null,2)); loadAll();
}

async function generateVideo() {
  const r = await api('/v1/generate/video', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({topic:document.getElementById('vid-topic').value, prompt:document.getElementById('vid-prompt').value,
      duration:parseInt(document.getElementById('vid-duration').value), quality:document.getElementById('vid-quality').value})});
  status(JSON.stringify(r,null,2)); loadAll();
}

async function addRequest() {
  const r = await api('/v1/request', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({content_type:document.getElementById('req-type').value, topic:document.getElementById('req-topic').value,
      priority:document.getElementById('req-priority').value, quality:document.getElementById('req-quality').value})});
  status(JSON.stringify(r,null,2)); loadAll();
}

async function createLesson() {
  const r = await api('/v1/lessons', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({topic:document.getElementById('lesson-topic').value, source_url:document.getElementById('lesson-source').value||null})});
  status(JSON.stringify(r,null,2)); loadAll();
}

async function register() { const r = await api('/v1/register',{method:'POST'}); status(JSON.stringify(r,null,2)); loadAll(); }
async function review() { const r = await api('/v1/review'); status(JSON.stringify(r,null,2)); loadAll(); }

async function approveItem(type, id) {
  let r;
  if (type==='music') r = await api('/v1/approve/music/'+id, {method:'POST'});
  else if (type==='podcast') r = await api('/v1/approve/podcast/'+id, {method:'POST'});
  else r = await api('/v1/assets/'+id+'/approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  status(JSON.stringify(r,null,2)); loadAll();
}

loadAll();
loadConnections();
setInterval(loadAll, 30000);
</script>
</body>
</html>"""

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(application: BlueWavesApplication, host: str = "127.0.0.1", port: int = 8787) -> None:
    handler = type("ConfiguredBlueWavesHandler", (BlueWavesHandler,), {"application": application})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Blue Waves listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
