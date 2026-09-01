from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from .governance import Governance
from .models import AssetStatus, Claim, ContentAsset, Language, SourceRef
from .providers import Completion, ProviderUnavailable, TextProvider


PILLAR = "the_operators_craft"


@dataclass(frozen=True)
class ResearchResult:
    topic: str
    angle: str
    sources: tuple[SourceRef, ...]
    questions: tuple[str, ...]
    produced_by: str = "MIRA"


class ResearchEngine:
    """MIRA's research engine. No source means no claim of trend or market fact."""

    def propose(self, topic: str, source_url: str | None = None, source_verified: bool = False) -> ResearchResult:
        source = SourceRef(
            source_id=f"owner-{uuid.uuid4().hex[:8]}",
            title="Owner-supplied source link" if source_url else "Owner-supplied operational experience",
            url=source_url,
            verified=source_verified,
        )
        return ResearchResult(
            topic=topic,
            angle="Explain the operational problem, show the math or process, then demonstrate the lesson in plain language.",
            sources=(source,),
            questions=(
                "What is the operational problem?",
                "What does the calculation or process actually do?",
                "What should a practitioner do next?",
            ),
        )


class ScriptEngine:
    """ZACK's bilingual script engine with a local-first/cloud-escalation boundary."""

    def __init__(self, local: TextProvider | None, cloud: TextProvider | None, governance: Governance):
        self.local = local
        self.cloud = cloud
        self.governance = governance

    def _fallback(self, result: ResearchResult, language: Language) -> str:
        if language is Language.EN:
            return (
                f"Today we will explain {result.topic}.\n\n"
                f"The practical question is simple: {result.questions[0]}\n"
                f"The answer is not a slogan. We will walk through the method, show what it measures, "
                "and end with the decision it helps a real operator make.\n\n"
                "This lesson is based on the owner's documented operational experience. "
                "Where a claim is not independently sourced, we will say so plainly."
            )
        return (
            f"اليوم سنشرح موضوع: {result.topic}.\n\n"
            f"السؤال العملي بسيط: {result.questions[0]}\n"
            "الإجابة ليست شعاراً. سنشرح الطريقة خطوة بخطوة، ونوضح ما الذي تقيسه، "
            "ثم ننهي بالقرار الذي تساعد الموظف أو المدير على اتخاذه.\n\n"
            "يعتمد هذا الدرس على خبرة تشغيلية موثقة لدى صاحب المشروع. "
            "وأي معلومة لم يتم التحقق منها بشكل مستقل سنذكر ذلك بوضوح."
        )

    def write(self, result: ResearchResult, language: Language) -> tuple[str, str, str]:
        system = (
            "You are ZACK, an educational content writer. Write a clear, humane, non-hype lesson. "
            "Preserve uncertainty. Do not invent statistics, sources, customers or outcomes."
        )
        user = f"Write a 3-minute {language.value} educational script about: {result.topic}. Angle: {result.angle}."
        providers: list[TextProvider] = []
        if language is Language.AR and self.cloud is not None:
            providers.append(self.cloud)
        if self.local is not None:
            providers.append(self.local)
        for provider in providers:
            try:
                completion = provider.complete(system, user)
                return completion.text, provider.name, completion.mode
            except ProviderUnavailable:
                continue
        return self._fallback(result, language), "deterministic_fallback", "local"

    def create_assets(self, result: ResearchResult, lesson_id: str | None = None) -> tuple[ContentAsset, ContentAsset]:
        assets: list[ContentAsset] = []
        for language in (Language.AR, Language.EN):
            body, provider, mode = self.write(result, language)
            source_refs = result.sources
            claim = Claim(
                claim_id=f"claim-{uuid.uuid4().hex[:8]}",
                text=f"Owner experience informs the lesson about {result.topic}.",
                source_refs=source_refs,
                status="verified" if any(ref.verified for ref in source_refs) else "unverified",
            )
            asset = ContentAsset(
                asset_id=f"bw-{language.value}-{uuid.uuid4().hex[:10]}",
                tenant_id=self.governance.policy.tenant_id,
                topic=result.topic,
                pillar=PILLAR,
                language=language,
                status=AssetStatus.RESEARCHED,
                body=body,
                claims=[claim],
                lesson_id=lesson_id,
                created_by="ZACK",
                provenance=[f"script_provider:{provider}", f"inference_mode:{mode}"],
            )
            assets.append(asset)
        return assets[0], assets[1]


class FactCheckEngine:
    """ANDY's content gate: unsupported claims remain visible and block readiness."""

    def __init__(self, governance: Governance):
        self.governance = governance

    def review(self, asset: ContentAsset) -> list[str]:
        unsupported = self.governance.validate_claims(asset)
        if unsupported:
            asset.provenance.append("andy_review:unproven_claims_present")
            return unsupported
        asset.transition(AssetStatus.SCRIPTED)
        asset.transition(AssetStatus.FACT_CHECKED)
        asset.provenance.append("andy_review:passed")
        return []


class ProductionEngine:
    """BELAL's hybrid production planner.

    It emits a manifest and shell-safe command plan. Actual render workers can be
    swapped between Linux and Windows without changing Blue Waves' business state.
    """

    def __init__(self, governance: Governance, tools: dict[str, str | None] | None = None):
        self.governance = governance
        self.tools = tools or {}

    def plan(self, asset: ContentAsset, output_dir: str = "assets/generated") -> dict[str, Any]:
        if asset.status is not AssetStatus.FACT_CHECKED:
            raise ValueError("asset must pass fact-check before production")
        ffmpeg = self.tools.get("ffmpeg") or "ffmpeg"
        voice = self.tools.get("voice") or "piper"
        music = self.tools.get("music") or "ACE-Step/local"
        manifest = {
            "asset_id": asset.asset_id,
            "language": asset.language.value,
            "mode": "hybrid",
            "render_backend": "linux_local_stills_plus_optional_cloud_motion",
            "fallback": "slides_ken_burns_captions",
            "steps": [
                {"stage": "narration", "tool": voice, "local": True},
                {"stage": "music", "tool": music, "local": True},
                {"stage": "motion", "tool": "deferred_verified_cloud_provider", "local": False, "optional": True},
                {"stage": "assembly", "tool": ffmpeg, "local": True, "encoder": "h264_amf_or_libx264"},
            ],
            "output_dir": output_dir,
            "golden_asset_required": True,
        }
        asset.media_manifest = manifest
        asset.transition(AssetStatus.PRODUCED)
        asset.transition(AssetStatus.AWAITING_OWNER)
        asset.provenance.append("belal_manifest:hybrid_fallback_ready")
        return manifest
