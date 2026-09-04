from __future__ import annotations

import math
import os
import tempfile
import uuid
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable

from .config import Settings
from .dialogue import build_narration
from .governance import Governance
from .models import AssetStatus, ContentAsset, Language, now_iso
from .providers import ProviderHealthMonitor, ProviderRegistry, ProviderUnavailable
from .video_use_editor import VideoUseEditor


# Videos at or above this length render as multiple scenes (each ~30s) that are
# concatenated before post-production. A single 180s KenBurns render is slow and
# monotonous; scenes keep pacing tight and give viewers chapter structure.
MULTI_SCENE_THRESHOLD = 60
SCENE_TARGET_SECONDS = 30
MAX_SCENES = 8


def split_narration_sections(narration: str, num_scenes: int) -> list[str]:
    """Split narration into ``num_scenes`` word-balanced sections by sentence."""
    sentences = [s.strip() for s in narration.replace("\n", " ").split(".") if s.strip()]
    if not sentences:
        return [narration] * num_scenes
    total_words = sum(len(s.split()) for s in sentences)
    target = max(1, total_words // num_scenes)
    sections: list[str] = []
    current: list[str] = []
    current_words = 0
    for sentence in sentences:
        words = len(sentence.split())
        if current and current_words + words > target * 1.4 and len(sections) < num_scenes - 1:
            sections.append(". ".join(current) + ".")
            current, current_words = [], 0
        current.append(sentence)
        current_words += words
    if current:
        sections.append(". ".join(current) + ".")
    while len(sections) < num_scenes:
        sections.append(sections[-1])
    return sections[:num_scenes]


@dataclass
class VideoGenerationResult:
    success: bool
    asset: ContentAsset | None = None
    video_path: str | None = None
    provider_used: str = ""
    error: str | None = None


class VideoEngine:
    """Video generation engine with quality-aware provider routing."""

    def __init__(self, settings: Settings, governance: Governance,
                 provider_registry: ProviderRegistry | None = None,
                 health_monitor: ProviderHealthMonitor | None = None) -> None:
        self._settings = settings
        self._governance = governance
        self._providers = provider_registry
        self._health = health_monitor or ProviderHealthMonitor()
        self._video_use_enabled = getattr(settings, "video_use_enabled", True)
        self._video_use_editor: VideoUseEditor | None = None
        if self._video_use_enabled:
            try:
                self._video_use_editor = VideoUseEditor(settings)
            except Exception:
                self._video_use_editor = None

    def generate(self, topic: str, prompt: str, duration: int = 5,
                 resolution: str | None = None, quality: str = "high",
                 preferred_provider: str | None = None,
                 narration: str | None = None, music_mode: str = "ambient",
                 progress_cb: Callable[[str, float], None] | None = None) -> VideoGenerationResult:
        # Best quality means 1080p. Previously every render was pinned to 720p,
        # so "high" produced the same output as "draft".
        if not resolution:
            resolution = "1080p" if quality in ("high", "premium") else "720p"

        # Videos are always narrated in English. When no narration is supplied,
        # build one from the topic sized to the requested runtime so the topic is
        # actually covered instead of being repeated or cut off mid-sentence.
        if not (narration or "").strip():
            narration = build_narration(topic, duration)
        if progress_cb:
            progress_cb("narration ready", 5.0)

        asset_id = f"video-{uuid.uuid4().hex[:12]}"
        asset = ContentAsset(
            asset_id=asset_id,
            tenant_id=self._settings.tenant_id,
            topic=topic,
            pillar="education",
            language=Language.EN,
            status=AssetStatus.PRODUCED,
        )

        providers = self._provider_candidates(preferred_provider, quality)
        is_long = duration >= MULTI_SCENE_THRESHOLD
        num_scenes = min(MAX_SCENES, max(2, duration // SCENE_TARGET_SECONDS)) if is_long else 1
        scene_duration = duration / num_scenes
        sections = split_narration_sections(narration, num_scenes) if is_long else [narration]
        chapters = [
            (round(i * scene_duration, 1), f"{topic} — Part {i + 1}/{num_scenes}")
            for i in range(num_scenes)
        ] if is_long else []

        errors: list[str] = []
        for provider in providers:
          reservation = None
          try:
            if self._providers:
                reservation = self._providers.rotation.reserve(
                    provider.name,
                    monthly_budget_cents=self._settings.monthly_cloud_cents,
                )
                if reservation is None:
                    errors.append(f"{provider.name}: quota or budget unavailable")
                    continue
            video_path = str(Path(self._settings.data_dir) / "videos" / f"{asset_id}.mp4")
            Path(video_path).parent.mkdir(parents=True, exist_ok=True)
            if is_long:
                self._render_scenes(
                    provider, prompt, sections, scene_duration, num_scenes,
                    resolution, music_mode, video_path, progress_cb,
                )
            else:
                # Ken Burns provider supports narration and music_mode
                if provider.name == "ken_burns":
                    video_bytes = provider.generate(
                        prompt=prompt, duration=duration, resolution=resolution,
                        narration=narration, music_mode=music_mode
                    )
                else:
                    video_bytes = provider.generate(prompt=prompt, duration=duration, resolution=resolution)
                Path(video_path).write_bytes(video_bytes)
            if progress_cb:
                progress_cb("scenes rendered", 55.0)

            # Post-production via video-use: overlays, transitions, color grading,
            # captioning, chapter cards, YouTube-spec encoding. This bridges the
            # quality gap between "raw render" and "real YouTube video".
            if self._video_use_editor:
                try:
                    if progress_cb:
                        progress_cb("post-production (video-use)", 60.0)
                    edit_result = self._video_use_editor.edit(
                        raw_video_path=Path(video_path),
                        transcript_text=narration or prompt,
                        narration_audio_path=None,
                        topic=topic,
                        duration=duration,
                        width=1920 if quality in ("high", "premium") else 1280,
                        height=1080 if quality in ("high", "premium") else 720,
                        chapters=chapters,
                    )
                    if edit_result.success and edit_result.output_path:
                        # Replace raw video with post-produced version.
                        # shutil.move survives cross-drive temp dirs where rename fails;
                        # the raw file is only removed after the move succeeds.
                        import shutil
                        tmp_out = Path(edit_result.output_path)
                        raw = Path(video_path)
                        backup = raw.with_name(raw.stem + ".raw" + raw.suffix)
                        raw.replace(backup)
                        try:
                            shutil.move(str(tmp_out), str(raw))
                        except Exception:
                            backup.replace(raw)
                            raise
                        backup.unlink(missing_ok=True)
                        asset.metadata["video_use"] = {
                            "transcript": edit_result.transcript[:500],
                            "edl_entries": len(edit_result.edl),
                            "self_eval_score": edit_result.self_eval_score,
                            "issues": edit_result.issues[:5],
                            "chapters": len(chapters),
                        }
                except Exception as exc:
                    # Post-production failure is not fatal — raw video is still usable
                    asset.metadata["video_use_error"] = str(exc)[:200]
            if progress_cb:
                progress_cb("post-production done", 90.0)

            asset.media_manifest = {"video_path": video_path, "provider": provider.name, "provider_attempts": [p.name for p in providers], "duration": duration, "resolution": resolution,
                                    "scenes": num_scenes, "chapters": [c[1] for c in chapters]}
            asset.transition(AssetStatus.AWAITING_OWNER)
            self._health.record_success(provider.name)
            if progress_cb:
                progress_cb("done", 95.0)
            return VideoGenerationResult(
                success=True,
                asset=asset,
                video_path=video_path,
                provider_used=provider.name,
            )
          except Exception as exc:
            if reservation is not None and self._providers:
                self._providers.rotation.release(reservation)
            self._health.record_failure(provider.name, str(exc))
            errors.append(f"{provider.name}: {exc}")
        asset.transition(AssetStatus.REJECTED)
        return VideoGenerationResult(success=False, asset=asset, error="; ".join(errors))

    def _render_scenes(self, provider: Any, prompt: str, sections: list[str],
                       scene_duration: float, num_scenes: int, resolution: str,
                       music_mode: str, video_path: str,
                       progress_cb: Callable[[str, float], None] | None = None) -> None:
        """Render one clip per narration section, then concatenate.

        Scenes vary visually (part-tagged prompt) so a 3-minute video does not
        look like a single frozen slide. Uses stream-copy concat with a
        re-encode fallback.
        """
        tmpdir = Path(tempfile.mkdtemp(prefix="bw-scenes-"))
        scene_files: list[Path] = []
        try:
            for i, section in enumerate(sections):
                scene_prompt = f"{prompt} (part {i + 1} of {num_scenes})"
                scene_dur = math.ceil(scene_duration)
                if provider.name == "ken_burns":
                    scene_bytes = provider.generate(
                        prompt=scene_prompt, duration=scene_dur, resolution=resolution,
                        narration=section, music_mode=music_mode,
                    )
                else:
                    scene_bytes = provider.generate(
                        prompt=scene_prompt, duration=scene_dur, resolution=resolution)
                scene_file = tmpdir / f"scene-{i:02d}.mp4"
                scene_file.write_bytes(scene_bytes)
                scene_files.append(scene_file)
                if progress_cb:
                    progress_cb(f"scene {i + 1}/{num_scenes} rendered",
                                5.0 + 50.0 * (i + 1) / num_scenes)
            self._concat_scenes(scene_files, Path(video_path))
        finally:
            for path in scene_files:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            try:
                tmpdir.rmdir()
            except OSError:
                pass

    @staticmethod
    def _concat_scenes(scene_files: list[Path], output: Path) -> None:
        """Join scene clips end to end (stream copy, re-encode fallback)."""
        list_file = output.parent / f"{output.stem}.concat.txt"
        try:
            list_file.write_text(
                "".join(f"file '{path.as_posix()}'\n" for path in scene_files),
                encoding="utf-8",
            )
            copy_cmd = [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                "-i", str(list_file), "-c", "copy", str(output),
            ]
            probe = subprocess.run(copy_cmd, capture_output=True, timeout=300)
            if probe.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
                re_cmd = [
                    "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(list_file), "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-c:a", "aac", "-b:a", "192k", str(output),
                ]
                subprocess.run(re_cmd, check=True, timeout=600, capture_output=True)
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("scene concat produced empty output")
        finally:
            try:
                list_file.unlink()
            except FileNotFoundError:
                pass

    def _provider_candidates(self, preferred_provider: str | None, quality: str) -> list[Any]:
        if self._providers:
            preferred = preferred_provider if preferred_provider else ("kling" if quality in ("high", "premium") else "seedance" if quality == "standard" else "ken_burns")
            return self._providers.configured_media_candidates("video", preferred, quality)
        return [self._select_video_provider(preferred_provider or self._select_provider(quality))]

    def _select_provider(self, quality: str) -> str:
        quality_map = {
            "draft": "ken_burns",
            "standard": "seedance",
            "high": "kling",
            "premium": "kling",
        }
        return quality_map.get(quality, "ken_burns")

    def _select_video_provider(self, name: str) -> Any:
        if self._providers:
            try:
                return self._providers.get_video_provider(name)
            except ProviderUnavailable:
                return self._providers.get_video_provider("ken_burns")
        # A bare engine has no configured provider registry; retain the v0.1
        # contract-test behavior and fail closed. The application supplies the
        # registry, including the working local FFmpeg fallback.
        from .providers import DeferredMotionProvider
        return DeferredMotionProvider()

    def generate_slideshow(self, topic: str, slides: list[str], duration_per_slide: int = 5) -> VideoGenerationResult:
        prompt = f"educational slideshow about {topic} with slides: {', '.join(slides)}"
        return self.generate(
            topic=topic,
            prompt=prompt,
            duration=duration_per_slide * len(slides),
            resolution="720p",
            quality="draft",
            preferred_provider="ken_burns",
        )

    def generate_kinetic(self, topic: str, prompt: str, duration: int = 10) -> VideoGenerationResult:
        return self.generate(
            topic=topic,
            prompt=prompt,
            duration=duration,
            resolution="1080p",
            quality="high",
        )
