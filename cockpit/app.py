from __future__ import annotations

from typing import Any

from ..application import BlueWavesApplication


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
