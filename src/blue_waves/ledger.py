from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any


class AppendOnlyLedger:
    """Small local audit ledger with a SHA-256 hash chain.

    The ledger records what Blue Waves claims it did; it is not a replacement for Codex
    evidence. Every record carries tenant context and the previous record hash.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "GENESIS"
        last = "GENESIS"
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = json.loads(line)["record_hash"]
        return last

    def append(self, event_type: str, payload: dict[str, Any], tenant_id: str, actor: str) -> dict[str, Any]:
        previous_hash = self._last_hash()
        record = {
            "event_type": event_type,
            "tenant_id": tenant_id,
            "actor": actor,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        record["record_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def verify(self) -> tuple[bool, str]:
        previous = "GENESIS"
        if not self.path.exists():
            return True, "empty ledger"
        with self.path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                record_hash = record.pop("record_hash", None)
                if record.get("previous_hash") != previous:
                    return False, f"previous hash mismatch at line {index}"
                canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                if record_hash != expected:
                    return False, f"record hash mismatch at line {index}"
                previous = record_hash
        return True, "hash chain intact"


class JsonStore:
    """Simple tenant-scoped JSON store for the separate Blue Waves application."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save_asset(self, asset: Any) -> None:
        path = self.root / "assets.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asset.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def save_music(self, asset: Any) -> None:
        self._append("music.jsonl", asset.to_dict())

    def save_podcast(self, asset: Any) -> None:
        self._append("podcasts.jsonl", asset.to_dict())

    def _append(self, filename: str, payload: dict[str, Any]) -> None:
        with (self.root / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _latest(self, filename: str) -> list[dict[str, Any]]:
        path = self.root / filename
        if not path.exists():
            return []
        latest: dict[str, dict[str, Any]] = {}
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    raw = json.loads(line)
                    latest[raw["asset_id"]] = raw
        return list(latest.values())

    def latest_assets(self) -> list[dict[str, Any]]:
        return self._latest("assets.jsonl")

    def latest_music(self) -> list[dict[str, Any]]:
        return self._latest("music.jsonl")

    def latest_podcasts(self) -> list[dict[str, Any]]:
        return self._latest("podcasts.jsonl")

    def save_cost(self, event: Any) -> None:
        with (self.root / "costs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")

    def save_metric(self, event: Any) -> None:
        self._append_raw("metrics.jsonl", asdict(event))

    def latest_metrics(self) -> list[dict[str, Any]]:
        path = self.root / "metrics.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def save_memory(self, memory: Any) -> None:
        self._append_raw("memory.jsonl", memory.to_dict())

    def latest_memories(self) -> list[dict[str, Any]]:
        path = self.root / "memory.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _append_raw(self, filename: str, payload: dict[str, Any]) -> None:
        with (self.root / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
