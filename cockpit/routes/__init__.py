from __future__ import annotations

import json
from typing import Any

from ..app import CockpitApp


class CockpitRoutes:
    """HTTP routes for Cockpit web UI."""

    def __init__(self, cockpit: CockpitApp) -> None:
        self._cockpit = cockpit

    def dashboard(self) -> str:
        data = self._cockpit.get_dashboard_data()
        return json.dumps(data, indent=2)

    def pending_approvals(self) -> str:
        approvals = self._cockpit.get_pending_approvals()
        return json.dumps(approvals, indent=2)

    def approve(self, content_type: str, asset_id: str) -> str:
        result = self._cockpit.approve_content(content_type, asset_id)
        return json.dumps(result, indent=2)

    def add_request(self, content_type: str, topic: str, priority: str = "normal",
                    quality: str = "high") -> str:
        result = self._cockpit.add_request(content_type, topic, priority, quality)
        return json.dumps(result, indent=2)

    def queue_status(self) -> str:
        queue = self._cockpit.get_queue()
        return json.dumps(queue, indent=2)
