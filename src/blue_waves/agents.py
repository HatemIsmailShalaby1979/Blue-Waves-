from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BlueWavesAgent:
    agent_id: str
    name: str
    role: str
    tier: str
    authority: str
    reviewed_by: tuple[str, ...]
    can: tuple[str, ...]
    cannot: tuple[str, ...]


AGENTS: tuple[BlueWavesAgent, ...] = (
    BlueWavesAgent("mira", "MIRA", "Research & Market Analyst", "standard", "$0", ("ANDY", "MAYAR"),
                   ("propose sourced topics", "identify unanswered learner questions"), ("publish", "invent trends or sources")),
    BlueWavesAgent("zack", "ZACK", "Content Writer", "external_communication", "$0", ("ANDY", "MAYAR"),
                   ("write AR and EN lessons", "preserve uncertainty"), ("publish", "make unsupported factual claims")),
    BlueWavesAgent("belal", "BELAL", "Image & Video Producer", "external_communication", "$0", ("ANDY", "MAYAR"),
                   ("plan hybrid media renders", "assemble local fallback videos"), ("publish", "skip golden-asset checks")),
    BlueWavesAgent("mayar", "MAYAR", "Executive Assistant", "standard", "$0", ("ANDY",),
                   ("compress queues", "surface owner decisions"), ("decide for the owner", "approve its own summaries")),
    BlueWavesAgent("leo", "LEO", "Distribution Manager", "external_communication", "$0", ("ANDY", "Hatem"),
                   ("queue approved publication", "collect platform metrics"), ("publish without item approval", "like, follow, subscribe, comment")),
    BlueWavesAgent("joe", "JOE", "Finance Advisor", "advisory_action", "$0", ("ANDY",),
                   ("track costs, runway and revenue scenarios",), ("move money", "promise returns", "approve its own financial action")),
    BlueWavesAgent("nelly", "NELLY", "Legal Advisor", "catalog_only", "$0", (),
                   ("draft checklists and contract questions",), ("give binding legal advice", "sign or send contracts")),
    BlueWavesAgent("koyoshu", "KOYOSHU", "Business Analyst / Metacognition", "meta", "$0", ("ANDY", "SAMI", "Hatem"),
                   ("propose evidence-backed improvements",), ("apply proposals", "review its own governance loop")),
    BlueWavesAgent("shepo", "SHEPO", "Finance & Profit Strategist", "advisory_action", "$0", ("ANDY",),
                   ("track real costs per generation", "project revenue scenarios", "optimize provider spend",
                    "flag budget overruns", "recommend pricing tiers"),
                   ("move money", "promise returns", "approve its own financial actions")),
)


def roster() -> list[dict[str, object]]:
    return [
        {
            "id": agent.agent_id,
            "name": agent.name,
            "role": agent.role,
            "tier": agent.tier,
            "authority": agent.authority,
            "reviewed_by": list(agent.reviewed_by),
            "can": list(agent.can),
            "cannot": list(agent.cannot),
        }
        for agent in AGENTS
    ]
