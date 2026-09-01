from blue_waves.config import Settings
from blue_waves.governance import Governance, Policy
from blue_waves.hybrid import HybridRouter, Stage
from blue_waves.providers import OpenAICompatibleProvider


def router(budget=0, cloud=False):
    governance = Governance(Policy(monthly_cloud_cents=budget))
    local = OpenAICompatibleProvider("lm_studio", "http://127.0.0.1:1/v1", "local", mode="local")
    remote = OpenAICompatibleProvider("openrouter", "https://example.com/v1", "model", "secret") if cloud else None
    return HybridRouter(governance, local, remote)


def test_motion_falls_back_to_local_when_no_verified_cloud_provider():
    route = router().route(Stage.MOTION)
    assert route.mode == "local_fallback"
    assert route.provider == "ffmpeg"


def test_motion_uses_cloud_only_with_configured_budget():
    route = router(budget=1, cloud=True).route(Stage.MOTION)
    assert route.mode == "cloud"
    assert route.provider == "openrouter"


def test_bilingual_review_stays_local_when_budget_is_zero():
    route = router().route(Stage.BILINGUAL_REVIEW, cloud_requested=True)
    assert route.mode == "local"
    assert route.provider == "lm_studio"


def test_media_stages_are_local():
    route = router().route(Stage.ASSEMBLY)
    assert route.mode == "local"
    assert route.provider == "local_media_tools"
