from datetime import datetime, timezone

from blue_waves.provider_rotation import ProviderCapability, ProviderRotationMatrix


def test_rotation_reserves_and_releases_quota(tmp_path):
    matrix = ProviderRotationMatrix(tmp_path / "rotation.json")
    matrix.register(ProviderCapability("free_music", ("music",), free_tier=True, daily_quota=2, monthly_quota=5, estimated_cents=0))

    first = matrix.reserve("free_music")
    second = matrix.reserve("free_music")
    third = matrix.reserve("free_music")

    assert first is not None
    assert second is not None
    assert third is None
    assert matrix.snapshot()["providers"]["free_music"]["daily_remaining"] == 0

    matrix.release(second)
    assert matrix.snapshot()["providers"]["free_music"]["daily_remaining"] == 1


def test_rotation_resets_daily_and_monthly_usage(tmp_path):
    now = [datetime(2026, 9, 4, tzinfo=timezone.utc)]
    matrix = ProviderRotationMatrix(tmp_path / "rotation.json", now=lambda: now[0])
    matrix.register(ProviderCapability("free_video", ("video",), free_tier=True, daily_quota=1, monthly_quota=2, estimated_cents=0))
    assert matrix.reserve("free_video") is not None

    now[0] = datetime(2026, 9, 5, tzinfo=timezone.utc)
    assert matrix.reserve("free_video") is not None

    now[0] = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert matrix.reserve("free_video") is not None
    snapshot = matrix.snapshot()
    assert snapshot["providers"]["free_video"]["monthly_used"] == 1


def test_paid_provider_requires_budget(tmp_path):
    matrix = ProviderRotationMatrix(tmp_path / "rotation.json")
    matrix.register(ProviderCapability("paid", ("video",), estimated_cents=2))
    assert matrix.reserve("paid", monthly_budget_cents=0) is None
    assert matrix.reserve("paid", monthly_budget_cents=2) is not None


def test_order_prefers_free_and_quality(tmp_path):
    matrix = ProviderRotationMatrix(tmp_path / "rotation.json")
    matrix.register(ProviderCapability("local", ("music",), mode="local", free_tier=True, estimated_cents=0, quality_rank=20))
    matrix.register(ProviderCapability("free_cloud", ("music",), free_tier=True, estimated_cents=0, quality_rank=80))
    matrix.register(ProviderCapability("paid_cloud", ("music",), quality_rank=100, estimated_cents=1))
    assert matrix.ordered(["paid_cloud", "local", "free_cloud"]) == ["free_cloud", "local", "paid_cloud"]
