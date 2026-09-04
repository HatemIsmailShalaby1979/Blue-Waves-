"""Quota-aware provider rotation for zero-cost-first media generation.

Provider quotas are deliberately treated as configuration, not facts. A provider
with an unknown quota may still be used when it is explicitly approved and its
estimated cost fits the monthly budget, but it is never presented as guaranteed
free capacity.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    content_types: tuple[str, ...]
    mode: str = "cloud"
    free_tier: bool = False
    daily_quota: int | None = None
    monthly_quota: int | None = None
    credit_cost: int = 1
    estimated_cents: int = 1
    quality_rank: int = 50
    commercial_use: str = "unknown"


@dataclass(frozen=True)
class Reservation:
    token: str
    provider: str
    units: int
    estimated_cents: int


class ProviderRotationMatrix:
    """Persisted, thread-safe quota and spend reservations."""

    def __init__(self, path: Path | None = None, now: Any = None) -> None:
        self.path = path
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._capabilities: dict[str, ProviderCapability] = {}
        self._usage: dict[str, dict[str, Any]] = {}
        self._month_spend_cents = 0
        self._day = ""
        self._month = ""
        self._reservations: dict[str, Reservation] = {}
        self._load()

    def register(self, capability: ProviderCapability) -> None:
        with self._lock:
            self._capabilities[capability.name] = capability
            self._usage.setdefault(capability.name, {"daily_used": 0, "monthly_used": 0})
            self._refresh()
            self._save()

    def capability(self, provider: str) -> ProviderCapability | None:
        return self._capabilities.get(provider)

    def estimate(self, provider: str) -> tuple[int, int]:
        capability = self._capabilities.get(provider)
        if capability is None:
            return 1, 1
        return capability.credit_cost, capability.estimated_cents

    def eligible(self, provider: str, units: int = 1, monthly_budget_cents: int = 0) -> bool:
        with self._lock:
            self._refresh()
            capability = self._capabilities.get(provider)
            if capability is None:
                return False
            if capability.mode == "cloud" and capability.estimated_cents > 0:
                if monthly_budget_cents <= 0 or self._month_spend_cents + capability.estimated_cents * units > monthly_budget_cents:
                    return False
            usage = self._usage.setdefault(provider, {"daily_used": 0, "monthly_used": 0})
            if capability.daily_quota is not None and usage["daily_used"] + units > capability.daily_quota:
                return False
            if capability.monthly_quota is not None and usage["monthly_used"] + units > capability.monthly_quota:
                return False
            return True

    def reserve(self, provider: str, units: int = 1, monthly_budget_cents: int = 0) -> Reservation | None:
        if units <= 0:
            raise ValueError("reservation units must be positive")
        with self._lock:
            if not self.eligible(provider, units, monthly_budget_cents):
                return None
            capability = self._capabilities[provider]
            usage = self._usage.setdefault(provider, {"daily_used": 0, "monthly_used": 0})
            usage["daily_used"] += units
            usage["monthly_used"] += units
            estimated = capability.estimated_cents * units
            self._month_spend_cents += estimated
            reservation = Reservation(uuid.uuid4().hex, provider, units, estimated)
            self._reservations[reservation.token] = reservation
            self._save()
            return reservation

    def release(self, reservation: Reservation | None) -> None:
        if reservation is None:
            return
        with self._lock:
            current = self._reservations.pop(reservation.token, None)
            if current is None:
                return
            usage = self._usage.setdefault(current.provider, {"daily_used": 0, "monthly_used": 0})
            usage["daily_used"] = max(0, usage["daily_used"] - current.units)
            usage["monthly_used"] = max(0, usage["monthly_used"] - current.units)
            self._month_spend_cents = max(0, self._month_spend_cents - current.estimated_cents)
            self._save()

    def ordered(self, providers: list[str], preferred: str | None = None, quality: str = "free") -> list[str]:
        with self._lock:
            self._refresh()
            unique = list(dict.fromkeys(name for name in providers if name in self._capabilities))
            if preferred in unique:
                unique.remove(preferred)
                unique.insert(0, preferred)
            head = unique[:1] if preferred in unique else []
            tail = unique[1:] if head else unique
            prefer_quality = quality in {"high", "premium", "standard"}
            tail.sort(key=lambda name: (
                0 if (prefer_quality and not self._capabilities[name].free_tier) else 1,
                0 if (not prefer_quality and self._capabilities[name].free_tier) else 1,
                -self._capabilities[name].quality_rank,
            ))
            return head + tail

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._refresh()
            result: dict[str, Any] = {
                "day": self._day,
                "month": self._month,
                "month_spend_cents": self._month_spend_cents,
                "providers": {},
            }
            for name, capability in self._capabilities.items():
                usage = self._usage.get(name, {"daily_used": 0, "monthly_used": 0})
                result["providers"][name] = {
                    **asdict(capability),
                    "content_types": list(capability.content_types),
                    "daily_used": usage["daily_used"],
                    "monthly_used": usage["monthly_used"],
                    "daily_remaining": None if capability.daily_quota is None else max(0, capability.daily_quota - usage["daily_used"]),
                    "monthly_remaining": None if capability.monthly_quota is None else max(0, capability.monthly_quota - usage["monthly_used"]),
                }
            return result

    def _refresh(self) -> None:
        current = self._now()
        day = current.date().isoformat()
        month = current.strftime("%Y-%m")
        if self._day and self._day != day:
            for usage in self._usage.values():
                usage["daily_used"] = 0
        if self._month and self._month != month:
            for usage in self._usage.values():
                usage["monthly_used"] = 0
            self._month_spend_cents = 0
        self._day = day
        self._month = month

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            self._refresh()
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._refresh()
            return
        self._day = str(data.get("day", ""))
        self._month = str(data.get("month", ""))
        self._month_spend_cents = int(data.get("month_spend_cents", 0) or 0)
        self._usage = dict(data.get("usage", {}))
        self._refresh()

    def _save(self) -> None:
        if self.path is None:
            return
        payload = {
            "day": self._day,
            "month": self._month,
            "month_spend_cents": self._month_spend_cents,
            "usage": self._usage,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            # Generation must not fail only because the advisory accounting file
            # is unavailable; the in-memory reservation still protects this run.
            pass
