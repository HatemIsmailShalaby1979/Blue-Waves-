"""Monetization tooling: sponsor outreach pipeline and media-kit generation.

These are coordination tools that reduce the manual work of monetizing the
channel. They do NOT create accounts or submit applications on the owner's
behalf — the owner must apply to the YouTube Partner Program / AdSense and
reach out to prospective sponsors.

Sponsor prospects are persisted to ``data/sponsors.json`` (not secrets, but
still sensitive contact info; file perms are set to 0600).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import now_iso


@dataclass
class SponsorProspect:
    prospect_id: str
    name: str
    contact: str
    niche: str = ""
    status: str = "outreach"  # outreach, contacted, replied, negotiation, signed, declined
    budget_usd: float = 0.0
    notes: str = ""
    created_at: str = field(default_factory=now_iso)
    last_updated: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PIPELINE_STAGES = ["outreach", "contacted", "replied", "negotiation", "signed", "declined"]


def _now() -> str:
    return now_iso()


class SponsorTracker:
    """Persist and query the sponsor outreach pipeline."""

    def __init__(self, root: Path) -> None:
        self.path = root / "sponsors.json"

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def list_prospects(self) -> list[dict[str, Any]]:
        return [self._read()[pid] for pid in sorted(self._read())]

    def get(self, prospect_id: str) -> dict[str, Any]:
        records = self._read()
        if prospect_id not in records:
            raise KeyError(f"unknown prospect: {prospect_id}")
        return records[prospect_id]

    def upsert(self, prospect: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        pid = prospect.get("prospect_id")
        if not pid:
            pid = f"prospect-{len(data) + 1:03d}"
        record = {
            "prospect_id": pid,
            "name": prospect.get("name", ""),
            "contact": prospect.get("contact", ""),
            "niche": prospect.get("niche", ""),
            "status": prospect.get("status", "outreach"),
            "budget_usd": float(prospect.get("budget_usd", 0) or 0),
            "notes": prospect.get("notes", ""),
            "created_at": data.get(pid, {}).get("created_at") or _now(),
            "last_updated": _now(),
        }
        data[pid] = record
        self._write(data)
        return record

    def update_status(self, prospect_id: str, status: str) -> dict[str, Any]:
        if status not in PIPELINE_STAGES:
            raise ValueError(f"invalid status: {status}")
        data = self._read()
        if prospect_id not in data:
            raise KeyError(f"unknown prospect: {prospect_id}")
        data[prospect_id]["status"] = status
        data[prospect_id]["last_updated"] = _now()
        self._write(data)
        return data[prospect_id]

    def delete(self, prospect_id: str) -> bool:
        data = self._read()
        if prospect_id not in data:
            return False
        del data[prospect_id]
        self._write(data)
        return True

    def pipeline_summary(self) -> dict[str, int]:
        summary = {stage: 0 for stage in PIPELINE_STAGES}
        for record in self._read().values():
            stage = record.get("status", "outreach")
            summary[stage] = summary.get(stage, 0) + 1
        return summary


EMAIL_TEMPLATE = """Hi {name},

I run Blue Waves, an educational content channel (science, tech and language
learning) with {audience_summary}.

We are building out monetization and would love to explore a sponsorship or
partnership with {company}. I've attached our media kit with up-to-date reach
and engagement numbers.

Would you be open to a short call this week?

Best,
The Blue Waves Team
"""


class MediaKitGenerator:
    """Build a sponsor-facing summary of channel reach and engagement."""

    def __init__(self, metrics: list[dict[str, Any]] | None = None, assets: dict[str, int] | None = None) -> None:
        self._metrics = metrics or []
        self._assets = assets or {}

    def _totals(self) -> dict[str, float]:
        totals: dict[str, float] = {
            "view_count": 0.0,
            "like_count": 0.0,
            "comment_count": 0.0,
            "subscriber_count": 0.0,
        }
        for m in self._metrics:
            metric = m.get("metric")
            if metric in totals:
                totals[metric] += float(m.get("value", 0) or 0)
        return totals

    def generate(self, channel_name: str = "Blue Waves", channel_url: str = "") -> dict[str, Any]:
        totals = self._totals()
        total_assets = sum((self._assets or {}).values()) or len(self._metrics)
        audience_summary = (
            f"{int(totals['view_count']):,} total views and "
            f"{int(totals['subscriber_count']):,} subscribers across "
            f"{int(total_assets):,} published pieces"
        )
        return {
            "channel_name": channel_name,
            "channel_url": channel_url,
            "audience_summary": audience_summary,
            "totals": {k: int(v) for k, v in totals.items()},
            "content_breakdown": self._assets,
            "generated_at": _now(),
        }

    def outreach_email(self, prospect: dict[str, Any], company: str = "") -> str:
        kit = self.generate()
        return EMAIL_TEMPLATE.format(
            name=prospect.get("name", "there"),
            company=company or prospect.get("company") or prospect.get("name", "your company"),
            audience_summary=kit["audience_summary"],
        )
