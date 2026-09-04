"""Provider approval gating.

Cloud providers cost real money and their terms are legally binding. Before the
system routes any generation to a cloud provider the owner must explicitly
approve it (e.g. after verifying the account and accepting the provider's
terms). This module records those approvals and fails closed otherwise.

Approvals are persisted to ``data/provider_approvals.json`` and are *not*
secrets — they only record that the owner accepted the terms for a named
provider. The actual credentials stay in the (encrypted) connection store.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .models import now_iso


class ProviderNotApproved(RuntimeError):
    """Raised when a cloud provider is not approved for use."""


# Providers must be explicitly approved to be used. Local/free providers are
# always usable and therefore not listed here.
REQUIRE_APPROVAL = {
    "openrouter",
    "groq",
    "nvidia_nim",
    "cerebras",
    "huggingface",
    "suno_api",
    "aimlapi_music",
    "kai_music",
    "ace_step",
    "kokoro",
    "google_tts",
    "kling",
    "seedance",
    "stock",
}


class ProviderApprovalStore:
    """Persist and query owner approvals for cloud providers."""

    def __init__(self, root: Path) -> None:
        self.path = root / "provider_approvals.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def is_approved(self, provider: str) -> bool:
        record = self._read().get(provider)
        return bool(record and record.get("approved"))

    def approve(
        self,
        provider: str,
        actor: str,
        terms: str | None = None,
        terms_hash: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "provider": provider,
            "approved": True,
            "approved_by": actor,
            "approved_at": now_iso(),
            "terms": terms or "",
            "terms_hash": terms_hash or "",
        }
        data = self._read()
        data[provider] = record
        self._write(data)
        return record

    def revoke(self, provider: str) -> bool:
        data = self._read()
        if provider in data:
            del data[provider]
            self._write(data)
            return True
        return False

    def list_approvals(self) -> dict[str, dict[str, Any]]:
        approvals = self._read()
        return {
            name: {
                "approved": bool(rec.get("approved")),
                "approved_by": rec.get("approved_by"),
                "approved_at": rec.get("approved_at"),
            }
            for name, rec in approvals.items()
        }

    def approval_status(self) -> dict[str, dict[str, Any]]:
        approvals = self._read()
        return {
            name: {
                "provider": name,
                "approved": self.is_approved(name),
                "approved_by": approvals.get(name, {}).get("approved_by"),
                "approved_at": approvals.get(name, {}).get("approved_at"),
                "requires_approval": name in REQUIRE_APPROVAL,
            }
            for name in sorted(REQUIRE_APPROVAL)
        }

    def require(self, provider: str) -> None:
        """Raise if `provider` is a cloud provider that has not been approved."""
        if provider in REQUIRE_APPROVAL and not self.is_approved(provider):
            raise ProviderNotApproved(
                f"cloud provider '{provider}' is not approved; approve its terms in the Cockpit "
                f"before use"
            )
