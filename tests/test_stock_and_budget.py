"""Phase D: stock provider registration, Shorts geometry, segment budgeter."""
from __future__ import annotations

import pytest

from blue_waves.application import BlueWavesApplication
from blue_waves.config import Settings
from blue_waves.enhancement import RESOLUTIONS
from blue_waves.providers import StockVideoProvider


def _app(tmp_path, **overrides) -> BlueWavesApplication:
    settings = Settings(data_dir=tmp_path, youtube_upload_enabled=False, **overrides)
    return BlueWavesApplication(settings)


def test_shorts_resolution_defined():
    assert RESOLUTIONS["short"] == (720, 1280)


def test_stock_unregistered_without_keys(tmp_path):
    app = _app(tmp_path)
    assert "stock" not in app.provider_registry.list_providers()["video"]
    provider = StockVideoProvider()
    with pytest.raises(Exception):
        provider.generate(prompt="ocean waves", duration=2)


def test_stock_registered_with_key(tmp_path):
    app = _app(tmp_path, pexels_api_key="pk-test")
    assert "stock" in app.provider_registry.list_providers()["video"]
    cap = app.provider_registry.rotation.capability("stock")
    assert cap.free_tier is True and cap.estimated_cents == 0


def test_quote_free_provider(tmp_path):
    app = _app(tmp_path)
    quote = app.quote_video_job(180, "high", provider="stock")
    assert quote["estimated_cents"] == 0
    assert quote["affordable"] is True


def test_quote_metered_provider_math(tmp_path):
    app = _app(tmp_path)
    quote = app.quote_video_job(180, "high", provider="kling")
    assert quote["estimated_cents"] == 180 * 13
    # Untracked (no balance recorded) → allowed through in testing mode.
    assert quote["affordable"] is True
    app.finance.set_free_cents("kling", 100)
    quote = app.quote_video_job(180, "high", provider="kling")
    assert quote["affordable"] is False
    assert quote["free_remaining_cents"] == 100


def test_submit_refuses_over_budget_job(tmp_path):
    app = _app(tmp_path)
    app.finance.set_free_cents("kling", 100)
    with pytest.raises(ValueError, match="exceeds"):
        app.submit_video_job(topic="t", prompt="p", duration=180,
                             preferred_provider="kling")
