from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from blue_waves.providers import KenBurnsProvider


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Isolate the renderer from ffmpeg, the system temp dir, and font discovery."""
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(suffix: str = "", prefix: str = "tmp", **kwargs):
        kwargs.pop("dir", None)
        return real_mkstemp(suffix=suffix, prefix=prefix, dir=str(tmp_path), **kwargs)

    monkeypatch.setattr("blue_waves.providers.tempfile.mkstemp", fake_mkstemp)

    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args[0] if args else [], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("blue_waves.providers.subprocess.run", fake_run)
    # Force the font branch inside _caption_filter so _ffmpeg_escape(font) runs.
    monkeypatch.setattr("blue_waves.providers.find_font", lambda bold: "/dummy/font.ttf")
    return monkeypatch


def _fake_images(tmp_path: Path, count: int) -> list[Path]:
    return [tmp_path / f"img_{i}.jpg" for i in range(count)]


def test_ken_burns_render_single_image(patched: pytest.MonkeyPatch, tmp_path: Path) -> None:  # pylint: disable=redefined-outer-name  # pytest fixture injection
    provider = KenBurnsProvider()
    images = _fake_images(tmp_path, 1)
    patched.setattr(provider, "_generate_topic_images", lambda *a, **k: images)
    patched.setattr(provider, "_download_images", lambda *a, **k: [])
    out = provider._render_video("a scenic mountain", width=1280, height=720, duration=4, narration="hello world")
    assert isinstance(out, Path)
    assert out.exists()
    out.unlink(missing_ok=True)


def test_ken_burns_render_multi_image(patched: pytest.MonkeyPatch, tmp_path: Path) -> None:  # pylint: disable=redefined-outer-name  # pytest fixture injection
    provider = KenBurnsProvider()
    images = _fake_images(tmp_path, 2)
    patched.setattr(provider, "_generate_topic_images", lambda *a, **k: images)
    patched.setattr(provider, "_download_images", lambda *a, **k: [])
    out = provider._render_video("a city skyline at night", width=1920, height=1080, duration=30, narration="one two three")
    assert isinstance(out, Path)
    assert out.exists()
    out.unlink(missing_ok=True)


def test_ken_burns_render_gradient_fallback(patched: pytest.MonkeyPatch, tmp_path: Path) -> None:  # pylint: disable=redefined-outer-name  # pytest fixture injection
    provider = KenBurnsProvider()
    patched.setattr(provider, "_generate_topic_images", lambda *a, **k: [])
    patched.setattr(provider, "_download_images", lambda *a, **k: [])
    out = provider._render_video("no images available", width=1280, height=720, duration=3)
    assert isinstance(out, Path)
    assert out.exists()
    out.unlink(missing_ok=True)
