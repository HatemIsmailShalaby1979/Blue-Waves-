from __future__ import annotations

import json
import urllib.error
import urllib.request
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import ContentAsset, MetricEvent


# SSRF protection - allowlist for Codex endpoints
ALLOWED_CODEX_HOSTS = {
    "api.helixcodex.com",
    "codex.example.com",
    "localhost",
    "127.0.0.1",
}

def _validate_url(url: str) -> None:
    """Validate URL to prevent SSRF."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RuntimeError(f"Invalid URL scheme: {parsed.scheme}")
    
    hostname = parsed.hostname
    if not hostname:
        raise RuntimeError("URL missing hostname")
    
    # Allow localhost for local development
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return
    
    # Check against allowed hosts
    if hostname not in ALLOWED_CODEX_HOSTS:
        raise RuntimeError(f"Host not allowed: {hostname}")


class CodexClient(Protocol):
    def register_blue_waves(self) -> dict[str, Any]: ...
    def emit_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def request_evidence_pack(self) -> dict[str, Any]: ...


@dataclass
class HttpCodexClient:
    """External-client adapter. It never imports Helix Codex internals."""

    base_url: str
    tenant_id: str
    api_key: str | None = None
    timeout: int = 30

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Codex request failed at {path}: {exc}") from exc

    def register_blue_waves(self) -> dict[str, Any]:
        return self._post("/api/v1/tenants/register", {
            "tenant_id": self.tenant_id,
            "client_name": "Blue Waves",
            "data_mode": "live_customer",
            "actors": [
                {"id": "MIRA", "role": "research"},
                {"id": "ZACK", "role": "content_writer"},
                {"id": "BELAL", "role": "producer"},
                {"id": "MAYAR", "role": "owner_assistant"},
                {"id": "LEO", "role": "distribution"},
                {"id": "JOE", "role": "finance_advisor"},
                {"id": "NELLY", "role": "legal_advisor"},
                {"id": "KOYOSHU", "role": "metacognition"},
            ],
        })

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/v1/events", {
            "event_id": f"bw-event-{uuid.uuid4().hex}",
            "tenant_id": self.tenant_id,
            "event_type": event_type,
            "payload": payload,
        })

    def request_evidence_pack(self) -> dict[str, Any]:
        return self._post("/api/v1/evidence-packs", {"tenant_id": self.tenant_id})


@dataclass
class InMemoryCodexClient:
    """Contract-test adapter used until a real Codex HTTP endpoint is deployed."""

    tenant_id: str = "bluewaves"

    def __post_init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.registered = False

    def register_blue_waves(self) -> dict[str, Any]:
        self.registered = True
        return {
            "tenant_id": self.tenant_id,
            "data_mode": "live_customer",
            "activation": "contract_test_only",
            "warning": "No external Codex endpoint configured; no production claim is made.",
        }

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {"event_id": f"bw-event-{uuid.uuid4().hex}", "tenant_id": self.tenant_id, "event_type": event_type, "payload": payload}
        self.events.append(event)
        return {"accepted": True, "mode": "contract_test", **event}

    def request_evidence_pack(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "mode": "contract_test",
            "event_count": len(self.events),
            "audit_chain_intact": True,
            "live_customer_records": 0,
            "production_ready": False,
        }
