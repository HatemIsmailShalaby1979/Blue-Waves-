from __future__ import annotations

import pytest

from blue_waves.config import Settings
from blue_waves.finance import FinanceEngine
from blue_waves.governance import Governance, Policy
from blue_waves.music_engine import MusicEngine
from blue_waves.podcast_engine import PodcastEngine
from blue_waves.providers import ProviderHealthMonitor
from blue_waves.video_engine import VideoEngine


def test_music_engine_generate_with_in_memory_provider():
    settings = Settings()
    governance = Governance(Policy())
    engine = MusicEngine(settings, governance)
    result = engine.generate(topic="test", genre="cinematic", mood="happy", duration_seconds=60)
    assert result.success is False
    assert result.error is not None


def test_music_engine_compose_multiple():
    settings = Settings()
    governance = Governance(Policy())
    engine = MusicEngine(settings, governance)
    prompts = [
        {"topic": "topic1", "genre": "pop", "mood": "happy"},
        {"topic": "topic2", "genre": "rock", "mood": "energetic"},
    ]
    results = engine.compose_multiple(prompts)
    assert len(results) == 2
    assert all(not r.success for r in results)


def test_podcast_engine_generate():
    settings = Settings()
    governance = Governance(Policy())
    engine = PodcastEngine(settings, governance)
    result = engine.generate(topic="test", script="Hello world", duration_seconds=60)
    # Edge-TTS is now available locally, so this should succeed
    assert result.success is True
    assert result.tts_provider_used == "edge_tts"


def test_podcast_engine_generate_solo():
    settings = Settings()
    governance = Governance(Policy())
    engine = PodcastEngine(settings, governance)
    result = engine.generate_solo(topic="test", script="Hello world", duration_seconds=60)
    # Edge-TTS is now available locally, so this should succeed
    assert result.success is True
    assert result.tts_provider_used == "edge_tts"


def test_podcast_engine_generate_dialogue():
    settings = Settings()
    governance = Governance(Policy())
    engine = PodcastEngine(settings, governance)
    result = engine.generate_dialogue(
        topic="test", host_script="Host says hello",
        guest_script="Guest says hi back", duration_seconds=60,
    )
    # Edge-TTS is now available locally, so this should succeed
    assert result.success is True
    assert result.tts_provider_used == "edge_tts"


def test_video_engine_generate():
    settings = Settings()
    governance = Governance(Policy())
    engine = VideoEngine(settings, governance)
    result = engine.generate(topic="test", prompt="A beautiful sunset", duration=5)
    assert result.success is False
    assert result.error is not None


def test_video_engine_generate_slideshow():
    settings = Settings()
    governance = Governance(Policy())
    engine = VideoEngine(settings, governance)
    result = engine.generate_slideshow(topic="test", slides=["slide1", "slide2"])
    assert result.success is False


def test_video_engine_generate_kinetic():
    settings = Settings()
    governance = Governance(Policy())
    engine = VideoEngine(settings, governance)
    result = engine.generate_kinetic(topic="test", prompt="Kinetic typography")
    assert result.success is False


def test_finance_engine_log_cost():
    engine = FinanceEngine()
    engine.log_cost("ace_step", "music", "m1", credits=10, estimated_cents=0)
    assert engine.get_weekly_costs() == 0
    assert engine.get_content_costs("music") == 0


def test_finance_engine_set_free_tier():
    engine = FinanceEngine()
    engine.set_free_tier("ace_step", daily_credits=100, monthly_credits=1000)
    tier = engine.get_remaining_free_tier("ace_step")
    assert tier["daily_credits"] == 100
    assert tier["monthly_credits"] == 1000


def test_finance_engine_recommend_provider():
    engine = FinanceEngine()
    engine.set_free_tier("ace_step", daily_credits=100, monthly_credits=1000)
    provider = engine.recommend_provider("music", "free")
    assert provider == "ace_step"


def test_health_monitor_record_success():
    monitor = ProviderHealthMonitor()
    monitor.record_success("ace_step")
    assert monitor.is_healthy("ace_step") is True


def test_health_monitor_record_failure():
    monitor = ProviderHealthMonitor()
    monitor.record_failure("kling", "API error")
    assert monitor.is_healthy("kling") is True
    monitor.record_failure("kling", "API error")
    monitor.record_failure("kling", "API error")
    assert monitor.is_healthy("kling") is False


def test_health_monitor_get_fallback():
    monitor = ProviderHealthMonitor()
    assert monitor.get_fallback("kling") == "seedance"
    assert monitor.get_fallback("suno_api") == "aimlapi_music"
    assert monitor.get_fallback("kokoro") == "elevenlabs_tts"
    assert monitor.get_fallback("elevenlabs_tts") == "edge_tts"
    assert monitor.get_fallback("unknown") == "ken_burns"
