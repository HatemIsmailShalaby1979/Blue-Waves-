from __future__ import annotations

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from typing import Any

from .application import BlueWavesApplication


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
        if content_type == "music":
            return self._app.approve_music(asset_id)
        elif content_type == "podcast":
            return self._app.approve_podcast(asset_id)
        elif content_type == "video":
            asset = self._app.get_asset(asset_id)
            return self._app.owner_approve(asset)
        return {"error": f"unknown content type: {content_type}"}

    def add_request(self, content_type: str, topic: str, priority: str = "normal",
                    quality: str = "high") -> dict[str, Any]:
        request = self._app.add_content_request(content_type, topic, priority, quality)
        return request.to_dict()

    def get_queue(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._app.queue.get_all()]


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
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b''

        if path.startswith("/api/approve/"):
            parts = path.split("/")
            if len(parts) >= 4:
                content_type = parts[2]
                asset_id = parts[3]
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

    def get_dashboard_html(self) -> str:
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Blue Waves Cockpit</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0a; color: #e0e0e0; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        h1 { color: #4fc3f7; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 20px; }
        .card h2 { color: #81c784; margin-bottom: 15px; font-size: 1.2em; }
        .stat { display: flex; justify-content: space-between; margin: 8px 0; }
        .stat-label { color: #999; }
        .stat-value { color: #fff; font-weight: bold; }
        .btn { background: #4fc3f7; color: #000; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; margin: 4px; }
        .btn:hover { background: #81d4fa; }
        .btn-danger { background: #ef5350; }
        .btn-danger:hover { background: #f44336; }
        .form-group { margin: 10px 0; }
        .form-group label { display: block; color: #999; margin-bottom: 5px; }
        .form-group input, .form-group select { width: 100%; padding: 8px; background: #333; border: 1px solid #555; color: #fff; border-radius: 4px; }
        #status { padding: 10px; background: #1a1a1a; border-radius: 4px; margin-top: 20px; }
        .approval-item { background: #2a2a2a; padding: 15px; border-radius: 4px; margin: 10px 0; }
        .approval-item h3 { color: #ffb74d; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Blue Waves Cockpit v0.2.0</h1>
        <div class="grid">
            <div class="card">
                <h2>System Health</h2>
                <div id="health-status">Loading...</div>
            </div>
            <div class="card">
                <h2>Queue Status</h2>
                <div id="queue-status">Loading...</div>
            </div>
            <div class="card">
                <h2>Finance (SHIPO)</h2>
                <div id="finance-status">Loading...</div>
            </div>
            <div class="card">
                <h2>Pending Approvals</h2>
                <div id="approvals">Loading...</div>
            </div>
            <div class="card">
                <h2>Add Content Request</h2>
                <div class="form-group">
                    <label>Content Type</label>
                    <select id="content-type">
                        <option value="video">Video</option>
                        <option value="music">Music</option>
                        <option value="podcast">Podcast</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Topic</label>
                    <input type="text" id="topic" placeholder="Enter topic...">
                </div>
                <div class="form-group">
                    <label>Priority</label>
                    <select id="priority">
                        <option value="normal">Normal</option>
                        <option value="high">High</option>
                        <option value="low">Low</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Quality</label>
                    <select id="quality">
                        <option value="free">Free</option>
                        <option value="standard">Standard</option>
                        <option value="high">High</option>
                    </select>
                </div>
                <button class="btn" onclick="addRequest()">Add Request</button>
            </div>
        </div>
        <div id="status"></div>
    </div>

    <script>
        async function loadDashboard() {
            try {
                const response = await fetch('/api/dashboard');
                const data = await response.json();
                document.getElementById('health-status').innerHTML = `
                    <div class="stat"><span class="stat-label">Version:</span><span class="stat-value">${data.health.version}</span></div>
                    <div class="stat"><span class="stat-label">Ledger:</span><span class="stat-value">${data.health.ledger_intact ? 'Intact' : 'Broken'}</span></div>
                    <div class="stat"><span class="stat-label">Queue:</span><span class="stat-value">${data.queue.total}</span></div>
                `;
                document.getElementById('queue-status').innerHTML = `
                    <div class="stat"><span class="stat-label">Pending:</span><span class="stat-value">${data.queue.pending}</span></div>
                    <div class="stat"><span class="stat-label">Ready:</span><span class="stat-value">${data.queue.ready_to_publish}</span></div>
                    <div class="stat"><span class="stat-label">Published:</span><span class="stat-value">${data.queue.published}</span></div>
                `;
                document.getElementById('finance-status').innerHTML = `
                    <div class="stat"><span class="stat-label">Weekly:</span><span class="stat-value">$${(data.finance.weekly_costs / 100).toFixed(2)}</span></div>
                    <div class="stat"><span class="stat-label">Music:</span><span class="stat-value">$${(data.finance.music_costs / 100).toFixed(2)}</span></div>
                    <div class="stat"><span class="stat-label">Podcast:</span><span class="stat-value">$${(data.finance.podcast_costs / 100).toFixed(2)}</span></div>
                `;
            } catch (e) {
                console.error('Failed to load dashboard:', e);
            }
        }

        async function loadApprovals() {
            try {
                const response = await fetch('/api/approvals');
                const approvals = await response.json();
                let html = '';
                approvals.forEach(a => {
                    html += `<div class="approval-item">
                        <h3>${a.type.toUpperCase()}: ${a.title}</h3>
                        <button class="btn" onclick="approve('${a.type}', '${a.asset_id}')">Approve</button>
                        <button class="btn btn-danger" onclick="reject('${a.type}', '${a.asset_id}')">Reject</button>
                    </div>`;
                });
                document.getElementById('approvals').innerHTML = html || '<p>No pending approvals</p>';
            } catch (e) {
                console.error('Failed to load approvals:', e);
            }
        }

        async function approve(type, assetId) {
            try {
                const response = await fetch(`/api/approve/${type}/${assetId}`, { method: 'POST' });
                const result = await response.json();
                document.getElementById('status').innerHTML = `<p>Approved: ${JSON.stringify(result)}</p>`;
                loadApprovals();
            } catch (e) {
                console.error('Failed to approve:', e);
            }
        }

        async function addRequest() {
            try {
                const contentType = document.getElementById('content-type').value;
                const topic = document.getElementById('topic').value;
                const priority = document.getElementById('priority').value;
                const quality = document.getElementById('quality').value;
                const response = await fetch('/api/request', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content_type: contentType, topic, priority, quality })
                });
                const result = await response.json();
                document.getElementById('status').innerHTML = `<p>Request added: ${JSON.stringify(result)}</p>`;
            } catch (e) {
                console.error('Failed to add request:', e);
            }
        }

        loadDashboard();
        loadApprovals();
        setInterval(loadDashboard, 30000);
    </script>
</body>
</html>'''

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging."""
        pass


def start_cockpit(app: BlueWavesApplication, host: str = "0.0.0.0", port: int = 8420) -> None:
    """Start the Cockpit web server."""
    cockpit = CockpitApp(app)
    CockpitHTTPHandler.app = app
    CockpitHTTPHandler.cockpit = cockpit

    server = HTTPServer((host, port), CockpitHTTPHandler)
    print(f"Blue Waves Cockpit v0.2.0")
    print(f"Starting server on http://{host}:{port}")
    print(f"Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
