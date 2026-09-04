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

    def __init__(self, local: TextProvider | None, cloud: TextProvider | None, governance: Governance,
                 cloud_providers: Iterable[TextProvider] | None = None):
        self.local = local
        self.cloud = cloud
        self.governance = governance
        self.cloud_providers = list(cloud_providers or ([] if cloud is None else [cloud]))

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
        providers.extend(self.cloud_providers)
        if self.local is not None:
            providers.append(self.local)
        for provider in providers:
            try:
                completion = provider.complete(system, user)
                return completion.text, provider.name, completion.mode
            except ProviderUnavailable:
                continue
        return self._fallback(result, language), "deterministic_fallback", "local"

    def write_media_script(
        self,
        result: ResearchResult,
        language: Language = Language.EN,
        content_type: str = "video",
        target_seconds: int = 180,
        enhancement: str | None = None,
    ) -> tuple[str, str, str]:
        """Write narration for a media asset.

        The media pipeline (video, podcast) previously spoke the raw form input
        verbatim. This routes it through MIRA's research angle and ZACK's writing
        so narration is a script rather than a topic string. Returns
        (script, provider_name, inference_mode) and degrades to a deterministic
        outline when no text provider is reachable.
        """
        # Natural English narration runs ~150 wpm. Ask for slightly less so TTS
        # does not have to race to fill the target duration with filler.
        target_words = max(60, int(target_seconds * 2.3))
        system = (
            "You are ZACK, an educational content writer. Write narration to be spoken aloud. "
            "Use short sentences, concrete examples, and plain transitions. No hype, no filler, "
            "no invented statistics, sources, customers or outcomes. Never mention being an AI. "
            "Do not include stage directions, headings, markdown, or speaker labels."
        )
        brief = (
            f"Write a {target_seconds}-second {language.value} {content_type} narration of about "
            f"{target_words} words about: {result.topic}.\n"
            f"Angle: {result.angle}\n"
            f"It must answer: {'; '.join(result.questions)}\n"
            "Open with the operational problem, walk through the method or calculation, "
            "and close with the decision a practitioner should make."
        )
        if enhancement:
            brief += f"\nRevision note from the owner: {enhancement}"
        providers: list[TextProvider] = []
        providers.extend(self.cloud_providers)
        if self.local is not None:
            providers.append(self.local)
        for provider in providers:
            try:
                completion = provider.complete(system, brief)
                text = self._clean_spoken_text(completion.text, target_words)
                if text:
                    return text, provider.name, completion.mode
            except ProviderUnavailable:
                continue
        return self._media_fallback(result, language, content_type), "deterministic_fallback", "local"

    @staticmethod
    def _clean_spoken_text(text: str, target_words: int) -> str:
        """Strip formatting an LLM adds that TTS would read aloud verbatim."""
        if not text:
            return ""
        cleaned = re.sub(r"\*\*|__|^#+\s*|`", "", text, flags=re.MULTILINE)
        cleaned = re.sub(r"^[-*]\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*(host|guest|narrator|speaker)\s*:", "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
        cleaned = re.sub(r"\([^)]*\)", "", cleaned)
        lines = [line.strip() for line in cleaned.splitlines()]
        cleaned = " ".join(line for line in lines if line)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # A wildly over-length script makes TTS truncate mid-sentence.
        words = cleaned.split()
        if len(words) > target_words * 2:
            cleaned = " ".join(words[: target_words * 2]).rstrip(",;:") + "."
        return cleaned

    def _media_fallback(self, result: ResearchResult, language: Language, content_type: str) -> str:
        if language is Language.EN:
            return (
                f"{result.topic}. {result.questions[0]} "
                f"Here is the practical version. {result.angle} "
                f"We start with the problem as an operator meets it, then we work through the method "
                f"step by step, and we finish with the decision it supports. "
                f"{result.questions[1]} We answer that with the calculation itself, not with a slogan. "
                f"{result.questions[2]} That is the part you can act on today. "
                f"This is drawn from the owner's documented operational experience; "
                f"anything not independently sourced is stated as judgement, not fact."
            )
        return (
            f"{result.topic}. {result.questions[0]} "
            "إليك الصورة العملية. نبدأ بالمشكلة كما يواجهها المشغّل، ثم نمر على الطريقة خطوة بخطوة، "
            "وننتهي بالقرار الذي تدعمه. نجيب على السؤال بالحساب نفسه لا بشعار. "
            "هذا ما يمكنك تطبيقه اليوم. يعتمد هذا على خبرة تشغيلية موثقة؛ "
            "وما لم يُتحقق منه بشكل مستقل نذكره كرأي لا كحقيقة."
        )

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
