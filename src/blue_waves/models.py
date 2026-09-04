from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .compat import StrEnum


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AssetStatus(StrEnum):
    IDEA = "idea"
    RESEARCHED = "researched"
    SCRIPTED = "scripted"
    FACT_CHECKED = "fact_checked"
    PRODUCED = "produced"
    AWAITING_OWNER = "awaiting_owner"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    QUEUED = "queued"
    COMPOSING = "composing"
    MIXING = "mixing"
    VOICE_RECORDING = "voice_recording"
    QUALITY_CHECK = "quality_check"
    READY_TO_PUBLISH = "ready_to_publish"
    AUTO_APPROVED = "auto_approved"


class ContentType(StrEnum):
    VIDEO = "video"
    MUSIC = "music"
    PODCAST = "podcast"


class MusicGenre(StrEnum):
    POP = "pop"
    ROCK = "rock"
    JAZZ = "jazz"
    CLASSICAL = "classical"
    HIPHOP = "hiphop"
    ELECTRONIC = "electronic"
    AMBIENT = "ambient"
    FOLK = "folk"
    CINEMATIC = "cinematic"
    LOFI = "lofi"
    ARABIC_TRADITIONAL = "arabic_traditional"


class VideoQuality(StrEnum):
    DRAFT = "draft"
    STANDARD = "standard"
    HIGH = "high"
    PREMIUM = "premium"


class PodcastFormat(StrEnum):
    SOLO = "solo"
    DIALOGUE = "dialogue"
    INTERVIEW = "interview"


class Language(StrEnum):
    AR = "ar"
    EN = "en"


class ApprovalTier(StrEnum):
    STANDARD = "standard"
    EXTERNAL_COMMUNICATION = "external_communication"
    ADVISORY_ACTION = "advisory_action"
    IRREVERSIBLE = "irreversible"


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    title: str
    url: str | None = None
    accessed_at: str = field(default_factory=now_iso)
    verified: bool = False


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    source_refs: tuple[SourceRef, ...] = ()
    status: str = "unverified"

    @property
    def is_supported(self) -> bool:
        return self.status == "verified" and bool(self.source_refs) and all(ref.verified for ref in self.source_refs)


@dataclass
class ContentAsset:
    asset_id: str
    tenant_id: str
    topic: str
    pillar: str
    language: Language
    status: AssetStatus = AssetStatus.IDEA
    body: str = ""
    claims: list[Claim] = field(default_factory=list)
    lesson_id: str | None = None
    created_by: str = "MIRA"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    provenance: list[str] = field(default_factory=list)
    media_manifest: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    approval_id: str | None = None
    attempt: int = 1
    parent_asset_id: str | None = None
    rejection_reason: str | None = None
    quality_score: float | None = None
    quality_issues: list[str] = field(default_factory=list)

    def transition(self, target: AssetStatus) -> None:
        allowed: dict[AssetStatus, set[AssetStatus]] = {
            AssetStatus.IDEA: {AssetStatus.RESEARCHED, AssetStatus.REJECTED},
            AssetStatus.RESEARCHED: {AssetStatus.SCRIPTED, AssetStatus.REJECTED},
            AssetStatus.SCRIPTED: {AssetStatus.FACT_CHECKED, AssetStatus.REJECTED},
            AssetStatus.FACT_CHECKED: {AssetStatus.PRODUCED, AssetStatus.REJECTED},
            AssetStatus.PRODUCED: {AssetStatus.AWAITING_OWNER, AssetStatus.REJECTED},
            AssetStatus.AWAITING_OWNER: {AssetStatus.APPROVED, AssetStatus.REJECTED},
            AssetStatus.APPROVED: {AssetStatus.PUBLISHED, AssetStatus.REJECTED},
            AssetStatus.PUBLISHED: set(),
            AssetStatus.REJECTED: set(),
        }
        if target not in allowed[self.status]:
            raise ValueError(f"invalid asset transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = now_iso()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["language"] = self.language.value if isinstance(self.language, Language) else self.language
        data["status"] = self.status.value
        data["claims"] = [
            {
                **asdict(claim),
                "source_refs": [asdict(ref) for ref in claim.source_refs],
            }
            for claim in self.claims
        ]
        return data


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    asset_id: str
    tenant_id: str
    requested_by: str
    tier: ApprovalTier
    requested_at: str = field(default_factory=now_iso)
    decision: str = "pending"
    decided_by: str | None = None
    decided_at: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Publication:
    publication_id: str
    asset_id: str
    tenant_id: str
    channel: str
    language: Language
    scheduled_for: str | None
    published_at: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class MetricEvent:
    event_id: str
    tenant_id: str
    asset_id: str
    channel: str
    metric: str
    value: float
    observed_at: str = field(default_factory=now_iso)
    source: str = "owner_import"


@dataclass(frozen=True)
class CostEvent:
    event_id: str
    tenant_id: str
    stage: str
    provider: str
    amount_cents: int
    description: str
    recorded_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class ImprovementProposal:
    proposal_id: str
    tenant_id: str
    category: str
    summary: str
    evidence: tuple[str, ...]
    proposed_by: str = "KOYOSHU"
    status: str = "proposed"
    created_at: str = field(default_factory=now_iso)


def asset_from_dict(data: dict[str, Any]) -> ContentAsset:
    claims: list[Claim] = []
    for raw_claim in data.get("claims", []):
        refs = tuple(SourceRef(**ref) for ref in raw_claim.get("source_refs", []))
        claims.append(Claim(
            claim_id=raw_claim["claim_id"],
            text=raw_claim["text"],
            source_refs=refs,
            status=raw_claim.get("status", "unverified"),
        ))
    return ContentAsset(
        asset_id=data["asset_id"],
        tenant_id=data["tenant_id"],
        topic=data["topic"],
        pillar=data["pillar"],
        language=Language(data["language"]),
        status=AssetStatus(data.get("status", "idea")),
        body=data.get("body", ""),
        claims=claims,
        lesson_id=data.get("lesson_id"),
        created_by=data.get("created_by", "MIRA"),
        created_at=data.get("created_at", now_iso()),
        updated_at=data.get("updated_at", now_iso()),
        provenance=list(data.get("provenance", [])),
        media_manifest=dict(data.get("media_manifest", {})),
        metadata=dict(data.get("metadata", {})),
        approval_id=data.get("approval_id"),
        attempt=int(data.get("attempt", 1)),
        parent_asset_id=data.get("parent_asset_id"),
        rejection_reason=data.get("rejection_reason"),
        quality_score=data.get("quality_score"),
        quality_issues=list(data.get("quality_issues", [])),
    )


@dataclass
class MusicAsset:
    asset_id: str
    tenant_id: str
    title: str
    genre: str
    mood: str
    duration_seconds: int
    language: Language
    status: AssetStatus = AssetStatus.IDEA
    prompt: str = ""
    lyrics: str = ""
    audio_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    media_manifest: dict[str, Any] = field(default_factory=dict)
    provider: str = "ace_step"
    quality: str = "high"
    created_by: str = "BELAL"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    provenance: list[str] = field(default_factory=list)
    approval_id: str | None = None
    attempt: int = 1
    parent_asset_id: str | None = None
    rejection_reason: str | None = None
    quality_score: float | None = None
    quality_issues: list[str] = field(default_factory=list)

    def transition(self, target: AssetStatus) -> None:
        allowed: dict[AssetStatus, set[AssetStatus]] = {
            AssetStatus.IDEA: {AssetStatus.COMPOSING, AssetStatus.REJECTED},
            AssetStatus.COMPOSING: {AssetStatus.MIXING, AssetStatus.REJECTED},
            AssetStatus.MIXING: {AssetStatus.AWAITING_OWNER, AssetStatus.REJECTED},
            AssetStatus.AWAITING_OWNER: {AssetStatus.APPROVED, AssetStatus.REJECTED},
            AssetStatus.APPROVED: {AssetStatus.PUBLISHED, AssetStatus.REJECTED},
            AssetStatus.PUBLISHED: set(),
            AssetStatus.REJECTED: set(),
        }
        if target not in allowed[self.status]:
            raise ValueError(f"invalid music transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = now_iso()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["language"] = self.language.value if isinstance(self.language, Language) else self.language
        data["status"] = self.status.value
        return data


def music_asset_from_dict(data: dict[str, Any]) -> MusicAsset:
    return MusicAsset(
        asset_id=data["asset_id"],
        tenant_id=data["tenant_id"],
        title=data["title"],
        genre=data["genre"],
        mood=data["mood"],
        duration_seconds=data["duration_seconds"],
        language=Language(data["language"]),
        status=AssetStatus(data.get("status", "idea")),
        prompt=data.get("prompt", ""),
        lyrics=data.get("lyrics", ""),
        audio_path=data.get("audio_path"),
        metadata=dict(data.get("metadata", {})),
        media_manifest=dict(data.get("media_manifest", {})),
        provider=data.get("provider", "ace_step"),
        quality=data.get("quality", "high"),
        created_by=data.get("created_by", "BELAL"),
        created_at=data.get("created_at", now_iso()),
        updated_at=data.get("updated_at", now_iso()),
        provenance=list(data.get("provenance", [])),
        approval_id=data.get("approval_id"),
        attempt=int(data.get("attempt", 1)),
        parent_asset_id=data.get("parent_asset_id"),
        rejection_reason=data.get("rejection_reason"),
        quality_score=data.get("quality_score"),
        quality_issues=list(data.get("quality_issues", [])),
    )


@dataclass
class PodcastAsset:
    asset_id: str
    tenant_id: str
    title: str
    topic: str
    host_voice: str
    language: Language
    duration_target_seconds: int
    status: AssetStatus = AssetStatus.IDEA
    guest_voice: str | None = None
    format: str = "dialogue"
    script: str = ""
    audio_path: str | None = None
    music_intro_path: str | None = None
    music_outro_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    media_manifest: dict[str, Any] = field(default_factory=dict)
    tts_provider: str = "kokoro"
    music_provider: str = "ace_step"
    created_by: str = "ZACK"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    provenance: list[str] = field(default_factory=list)
    approval_id: str | None = None
    attempt: int = 1
    parent_asset_id: str | None = None
    rejection_reason: str | None = None
    quality_score: float | None = None
    quality_issues: list[str] = field(default_factory=list)

    def transition(self, target: AssetStatus) -> None:
        allowed: dict[AssetStatus, set[AssetStatus]] = {
            AssetStatus.IDEA: {AssetStatus.SCRIPTED, AssetStatus.REJECTED},
            AssetStatus.SCRIPTED: {AssetStatus.VOICE_RECORDING, AssetStatus.REJECTED},
            AssetStatus.VOICE_RECORDING: {AssetStatus.MIXING, AssetStatus.REJECTED},
            AssetStatus.MIXING: {AssetStatus.AWAITING_OWNER, AssetStatus.REJECTED},
            AssetStatus.AWAITING_OWNER: {AssetStatus.APPROVED, AssetStatus.REJECTED},
            AssetStatus.APPROVED: {AssetStatus.PUBLISHED, AssetStatus.REJECTED},
            AssetStatus.PUBLISHED: set(),
            AssetStatus.REJECTED: set(),
        }
        if target not in allowed[self.status]:
            raise ValueError(f"invalid podcast transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = now_iso()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["language"] = self.language.value if isinstance(self.language, Language) else self.language
        data["status"] = self.status.value
        return data


def podcast_asset_from_dict(data: dict[str, Any]) -> PodcastAsset:
    return PodcastAsset(
        asset_id=data["asset_id"],
        tenant_id=data["tenant_id"],
        title=data["title"],
        topic=data["topic"],
        host_voice=data["host_voice"],
        language=Language(data["language"]),
        duration_target_seconds=data["duration_target_seconds"],
        status=AssetStatus(data.get("status", "idea")),
        guest_voice=data.get("guest_voice"),
        format=data.get("format", "dialogue"),
        script=data.get("script", ""),
        audio_path=data.get("audio_path"),
        music_intro_path=data.get("music_intro_path"),
        music_outro_path=data.get("music_outro_path"),
        metadata=dict(data.get("metadata", {})),
        media_manifest=dict(data.get("media_manifest", {})),
        tts_provider=data.get("tts_provider", "kokoro"),
        music_provider=data.get("music_provider", "ace_step"),
        created_by=data.get("created_by", "ZACK"),
        created_at=data.get("created_at", now_iso()),
        updated_at=data.get("updated_at", now_iso()),
        provenance=list(data.get("provenance", [])),
        approval_id=data.get("approval_id"),
        attempt=int(data.get("attempt", 1)),
        parent_asset_id=data.get("parent_asset_id"),
        rejection_reason=data.get("rejection_reason"),
        quality_score=data.get("quality_score"),
        quality_issues=list(data.get("quality_issues", [])),
    )


@dataclass
class ContentRequest:
    id: str
    content_type: str
    topic: str
    priority: str = "normal"
    quality: str = "high"
    language: str = "en"
    stage: str = "queued"
    script: str | None = None
    music_path: str | None = None
    audio_path: str | None = None
    video_path: str | None = None
    publication: dict[str, Any] | None = None
    error: str | None = None
    estimated_cost_cents: int = 0
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def advance_stage(self) -> None:
        stages = ["queued", "scripted", "composed", "quality_check", "ready_to_publish", "published"]
        idx = stages.index(self.stage) if self.stage in stages else -1
        if 0 <= idx < len(stages) - 1:
            self.stage = stages[idx + 1]
            self.updated_at = now_iso()

    def set_error(self, error: str) -> None:
        self.error = error
        self.stage = "rejected"
        self.updated_at = now_iso()

    def approve_quality(self) -> None:
        self.stage = "ready_to_publish"
        self.updated_at = now_iso()

    def reject_quality(self, reason: str) -> None:
        self.error = reason
        self.stage = "rejected"
        self.updated_at = now_iso()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def content_request_from_dict(data: dict[str, Any]) -> ContentRequest:
    return ContentRequest(
        id=data["id"],
        content_type=data["content_type"],
        topic=data["topic"],
        priority=data.get("priority", "normal"),
        quality=data.get("quality", "high"),
        language=data.get("language", "en"),
        stage=data.get("stage", "queued"),
        script=data.get("script"),
        music_path=data.get("music_path"),
        audio_path=data.get("audio_path"),
        video_path=data.get("video_path"),
        publication=data.get("publication"),
        error=data.get("error"),
        estimated_cost_cents=data.get("estimated_cost_cents", 0),
        created_at=data.get("created_at", now_iso()),
        updated_at=data.get("updated_at", now_iso()),
    )
