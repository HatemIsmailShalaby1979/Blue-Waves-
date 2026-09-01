from pathlib import Path

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.models import AssetStatus, Language


def app(tmp_path):
    return BlueWavesApplication(Settings(data_dir=tmp_path))


def test_bilingual_lesson_creates_two_separate_assets(tmp_path):
    application = app(tmp_path)
    ar, en = application.create_bilingual_lesson("Erlang C for real operators")
    assert ar.language is Language.AR
    assert en.language is Language.EN
    assert ar.asset_id != en.asset_id
    assert ar.tenant_id == en.tenant_id == "bluewaves"
    assert ar.status is AssetStatus.RESEARCHED
    assert en.status is AssetStatus.RESEARCHED


def test_fact_check_blocks_unverified_claims(tmp_path):
    application = app(tmp_path)
    ar, _ = application.create_bilingual_lesson("Unverified lesson")
    result = application.fact_check_and_produce(ar)
    assert result["ready"] is False
    assert result["unsupported_claims"]
    assert ar.status is AssetStatus.RESEARCHED


def test_verified_source_reaches_owner_queue(tmp_path):
    application = app(tmp_path)
    ar, _ = application.create_bilingual_lesson(
        "Erlang C from an owner source",
        "https://example.com/source",
        source_verified=True,
    )
    result = application.fact_check_and_produce(ar)
    assert result["ready"] is True
    assert ar.status is AssetStatus.AWAITING_OWNER
    assert ar.media_manifest["mode"] == "hybrid"
    assert ar.media_manifest["fallback"] == "slides_ken_burns_captions"


def test_full_external_client_flow_requires_owner_approval(tmp_path):
    application = app(tmp_path)
    ar, en = application.create_bilingual_lesson(
        "A real bilingual lesson",
        "https://example.com/source",
        source_verified=True,
    )
    for asset in (ar, en):
        application.fact_check_and_produce(asset)
        application.owner_approve(asset)
        publication = application.publish(asset, "youtube")
        application.record_metric(asset, "youtube", "watch_time_seconds", 0, source="contract_test_placeholder")
        assert publication["approval_id"] == asset.approval_id
    assert len(application.codex.events) == 4


def test_weekly_review_never_applies_its_proposal(tmp_path):
    application = app(tmp_path)
    review = application.weekly_review()
    assert review["proposed_by"] == "KOYOSHU"
    assert review["apply"] is False
    assert review["status"] == "proposed"


def test_health_reports_contract_test_not_production(tmp_path):
    application = app(tmp_path)
    health = application.health()
    assert health["codex_adapter"] == "InMemoryCodexClient"
    assert health["cloud_motion"] == "deferred_until_verified_provider"
