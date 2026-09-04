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
        from .providers import without_local_pixels
        providers = without_local_pixels(providers, self._settings)
        is_long = duration >= MULTI_SCENE_THRESHOLD
        num_scenes = min(MAX_SCENES, max(2, duration // SCENE_TARGET_SECONDS)) if is_long else 1
        scene_duration = duration / num_scenes
        sections = split_narration_sections(narration, num_scenes) if is_long else [narration]
        chapters = [
            (round(i * scene_duration, 1), f"{topic} — Part {i + 1}/{num_scenes}")
            for i in range(num_scenes)
        ] if is_long else []

        errors: list[str] = []
        if not providers:
            asset.transition(AssetStatus.REJECTED)
            return VideoGenerationResult(
                success=False, asset=asset,
                error=("local pixel generation is disabled (BLUE_WAVES_ALLOW_LOCAL_FALLBACK=false) "
                       "and no cloud video provider is configured — add a funded Kling/native key, "
                       "use stock footage, or submit a shorter test render"),
            )
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

            # Cloud/stock clips carry no narration — mix a TTS bed over them so
            # every video is narrated regardless of which provider rendered it.
            if not getattr(provider, "provides_narration", provider.name == "ken_burns"):
                try:
                    if progress_cb:
                        progress_cb("narration bed", 57.0)
                    self._mix_narration_bed(video_path, narration or prompt, duration)
                    asset.metadata["narration_bed"] = True
                except Exception as exc:
                    asset.metadata["narration_bed_error"] = str(exc)[:200]

            # Post-production via video-use: overlays, transitions, color grading,
            # captioning, chapter cards, YouTube-spec encoding. This bridges the
            # quality gap between "raw render" and "real YouTube video".
            if self._video_use_editor:
                try:
                    if progress_cb:
                        progress_cb("post-production (video-use)", 60.0)
                    from .enhancement import RESOLUTIONS as _RES
                    out_w, out_h = _RES.get(
                        resolution or "",
                        ((1920, 1080) if quality in ("high", "premium") else (1280, 720)),
                    )
                    edit_result = self._video_use_editor.edit(
                        raw_video_path=Path(video_path),
                        transcript_text=narration or prompt,
                        narration_audio_path=None,
                        topic=topic,
                        duration=duration,
                        width=out_w,
                        height=out_h,
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

    def _mix_narration_bed(self, video_path: str, narration: str, duration: int) -> None:
        """Mix a TTS narration track over a provider clip that has none.

        Cloud and stock clips arrive without speech. The full narration is
        synthesized once (free Edge voice), padded to the video length, and
        mixed under it — clip ambience kept where present, narration kept
        everywhere. Assembly only: creates no visuals.
        """
        text = (narration or "").strip()
        if not text:
            return
        tts = None
        if self._providers:
            try:
                tts = self._providers.get_tts_provider("edge_tts")
            except Exception:
                tts = None
        if tts is None:
            from .providers import EdgeTTSProvider
            tts = EdgeTTSProvider()
        tmpdir = Path(tempfile.mkdtemp(prefix="bw-narr-"))
        try:
            parts: list[Path] = []
            for i in range(0, len(text), 8000):
                chunk = text[i:i + 8000]
                audio = tts.generate(text=chunk, voice_id="en-US-GuyNeural")
                part = tmpdir / f"narr-{i // 8000:02d}.mp3"
                part.write_bytes(audio)
                parts.append(part)
            if len(parts) == 1:
                narr_src = parts[0]
            else:
                narr_src = tmpdir / "narr.mp3"
                file_list = tmpdir / "parts.txt"
                file_list.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
                subprocess.run(
                    [self._settings.ffmpeg_bin, "-y", "-loglevel", "error",
                     "-f", "concat", "-safe", "0", "-i", str(file_list),
                     "-c", "copy", str(narr_src)],
                    check=True, timeout=120, capture_output=True,
                )
            mixed = tmpdir / "mixed.mp4"
            ambience_mix = [
                self._settings.ffmpeg_bin, "-y", "-loglevel", "error",
                "-i", video_path, "-i", str(narr_src),
                "-filter_complex",
                (f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.25[amb];"
                 f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=1.0,"
                 f"apad=whole_dur={duration}[sp];"
                 f"[amb][sp]amix=inputs=2:duration=longest:dropout_transition=2,"
                 f"atrim=0:{duration}[out]"),
                "-map", "0:v", "-map", "[out]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-t", str(duration), str(mixed),
            ]
            probe = subprocess.run(ambience_mix, capture_output=True,
                                   timeout=max(120, duration * 2 + 30))
            if probe.returncode != 0 or not mixed.is_file() or mixed.stat().st_size == 0:
                # Clip has no usable audio track — carry narration alone.
                subprocess.run(
                    [self._settings.ffmpeg_bin, "-y", "-loglevel", "error",
                     "-i", video_path, "-i", str(narr_src),
                     "-map", "0:v", "-map", "1:a",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-ar", "48000", "-ac", "2",
                     "-af", f"apad=whole_dur={duration}", "-t", str(duration),
                     str(mixed)],
                    check=True, timeout=max(120, duration * 2 + 30), capture_output=True,
                )
            if not mixed.is_file() or mixed.stat().st_size == 0:
                raise RuntimeError("narration mix produced empty output")
            os.replace(str(mixed), video_path)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

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
        # Last-frame continuation: providers with image-to-video start every
        # scene after the first from the previous scene's final frame. This is
        # what makes multi-clip AI video look continuous instead of 6 restarts.
        use_i2v = bool(getattr(provider, "supports_image_to_video", False))
        prev_frame: bytes | None = None
        try:
            for i, section in enumerate(sections):
                scene_prompt = f"{prompt} (part {i + 1} of {num_scenes})"
                scene_dur = math.ceil(scene_duration)
                if provider.name == "ken_burns":
                    scene_bytes = provider.generate(
                        prompt=scene_prompt, duration=scene_dur, resolution=resolution,
                        narration=section, music_mode=music_mode,
                    )
                elif use_i2v and prev_frame is not None:
                    scene_bytes = provider.generate_from_image(
                        prev_frame, scene_prompt, scene_dur)
                else:
                    scene_bytes = provider.generate(
                        prompt=scene_prompt, duration=scene_dur, resolution=resolution)
                scene_file = tmpdir / f"scene-{i:02d}.mp4"
                scene_file.write_bytes(scene_bytes)
                scene_files.append(scene_file)
                if use_i2v:
                    try:
                        prev_frame = self._extract_last_frame(scene_file)
                    except Exception:
                        prev_frame = None  # next scene falls back to text-to-video
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
    def _extract_last_frame(scene_file: Path) -> bytes:
        """Grab the final frame of a scene clip as JPEG bytes (i2v seed)."""
        fd, frame_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.5",
                 "-i", str(scene_file), "-frames:v", "1", "-q:v", "3", frame_path],
                check=True, timeout=60, capture_output=True,
            )
            payload = Path(frame_path).read_bytes()
            if not payload:
                raise RuntimeError("empty frame")
            return payload
        finally:
            try:
                Path(frame_path).unlink()
            except FileNotFoundError:
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
