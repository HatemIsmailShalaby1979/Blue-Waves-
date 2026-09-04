"""Deterministic post-generation enhancement and mastering pipeline."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .toolchain import AUDIO_SAMPLE_RATE, LOUDNORM_FILTER, Toolchain, audio_output_args


# Canonical delivery resolutions. Defined once so the renderer, the masterer
# and the quality gate can never disagree about what "1080p" means.
RESOLUTIONS: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
    # Vertical Shorts preset (YouTube Shorts: vertical, <=60s).
    "short": (720, 1280),
}


@dataclass
class EnhancementResult:
    output_path: Path
    profile: str
    steps: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    input_sha256: str = ""
    output_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "profile": self.profile,
            "steps": list(self.steps),
            "skipped": list(self.skipped),
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
        }


class EnhancementError(RuntimeError):
    pass


class MediaEnhancer:
    """FFmpeg-first enhancer; optional AI tools are additive, never required."""

    def __init__(self, toolchain: Toolchain | None = None, enabled: bool = True) -> None:
        self.toolchain = toolchain or Toolchain()
        self.enabled = enabled

    def master_audio(self, source: Path, target: Path, profile: str = "audio_master_v1") -> EnhancementResult:
        if not self.enabled:
            return self._copy_result(source, target, profile, "enhancement disabled")
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.toolchain.ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
            "-af", (
                f"aresample={AUDIO_SAMPLE_RATE}:resampler=soxr:precision=28,"
                f"aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,"
                f"{LOUDNORM_FILTER},alimiter=limit=0.95"
            ),
            "-c:a", "pcm_s24le", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2", str(target),
        ]
        self._run(command, max(60, 30 + _duration_budget(source)))
        return self._result(source, target, profile, ["soxr_resample", "stereo_normalize", "loudnorm", "true_peak_limit"])

    def master_music(self, source: Path, target: Path, profile: str = "music_master_v1") -> EnhancementResult:
        """Master music to YouTube/Spotify delivery spec.

        Targets -14 LUFS (streaming standard), adds multiband compression
        and stereo widening for a competitive, radio-ready sound.
        """
        if not self.enabled:
            return self._copy_result(source, target, profile, "enhancement disabled")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Music-specific chain: resample -> stereo -> loudnorm at -14 LUFS ->
        # gentle bus compression -> presence EQ -> limiter -> stereo widening.
        # (Uses equalizer/acompressor: portable across ffmpeg builds, unlike
        # firequalizer's version-sensitive gain_entry syntax.)
        command = [
            self.toolchain.ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
            "-af", (
                f"aresample={AUDIO_SAMPLE_RATE}:resampler=soxr:precision=28,"
                f"aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,"
                f"loudnorm=I=-14:TP=-1.5:LRA=11,"
                f"acompressor=threshold=-18dB:ratio=3:attack=20:release=200,"
                f"equalizer=f=250:t=q:w=1:g=1.5,"
                f"equalizer=f=4000:t=q:w=1:g=1.5,"
                f"equalizer=f=8000:t=h:g=2.5,"
                f"alimiter=limit=0.96,"
                f"stereotools=mlev=0.02:slev=0.03"
            ),
            "-c:a", "pcm_s24le", "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2", str(target),
        ]
        self._run(command, max(60, 30 + _duration_budget(source)))
        return self._result(source, target, profile, [
            "soxr_resample", "stereo_normalize", "loudnorm_-14lufs",
            "bus_compression", "presence_eq", "true_peak_limit", "stereo_widen",
        ])

    def master_video(self, source: Path, target: Path, resolution: str | None = None,
                     fps: int | None = None,
                     profile: str = "video_master_v1") -> EnhancementResult:
        """Master a rendered video for delivery.

        Geometry is *preserved* by default. The old signature defaulted to
        width=1280/height=720, so every high-quality 1080p render was silently
        downscaled during mastering — the render settings and the delivered
        file disagreed. Pass `resolution` ("1080p" etc.) only to explicitly
        re-target; it is still never allowed to shrink the source.
        """
        if not self.enabled:
            return self._copy_result(source, target, profile, "enhancement disabled")
        target.parent.mkdir(parents=True, exist_ok=True)
        src_w, src_h, src_fps = self._probe_video(source)

        # Resolve target geometry: explicit request wins, but never downscale.
        width, height = src_w, src_h
        if resolution:
            for label, (rw, rh) in RESOLUTIONS.items():
                if label.lower() == resolution.lower() and rw * rh > width * height:
                    width, height = rw, rh
                    break

        # yuv420p needs even dimensions; trunc() guarantees that without
        # letterboxing or rescaling the picture.
        out_fps = fps or src_fps or 30
        vf = (
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,"
            f"fps={out_fps},format=yuv420p,unsharp=5:5:0.35:5:5:0.0"
        )
        command = [
            self.toolchain.ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
            "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-profile:v", "high", "-level", "4.2",
            *audio_output_args(), "-movflags", "+faststart", str(target),
        ]
        self._run(command, max(90, 45 + _duration_budget(source) * 2))
        steps = ["lanczos_scale", "frame_rate_normalize", "unsharp",
                 "h264_crf18_slow", "high_profile", "audio_master"]
        if (width, height) != (src_w, src_h):
            steps.insert(0, f"upscale_{src_w}x{src_h}->{width}x{height}")
        return self._result(source, target, profile, steps)

    @staticmethod
    def _probe_video(path: Path) -> tuple[int, int, int]:
        """Return (width, height, fps) of the first video stream, or zeros."""
        import json
        import subprocess

        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,avg_frame_rate",
                 "-of", "json", str(path)],
                check=True, timeout=30, capture_output=True, text=True,
            ).stdout
            stream = (json.loads(out).get("streams") or [{}])[0]
            w = int(stream.get("width") or 0)
            h = int(stream.get("height") or 0)
            rate = str(stream.get("avg_frame_rate") or "0/1")
            num, _, den = rate.partition("/")
            fps = 0
            try:
                fps = int(round(float(num) / float(den))) if float(den or 0) else 0
            except (ValueError, ZeroDivisionError):
                fps = 0
            return w, h, fps
        except Exception:
            return 0, 0, 0

    def _run(self, command: list[str], timeout: int) -> None:
        try:
            self.toolchain.require()
            subprocess.run(command, check=True, timeout=timeout, capture_output=True)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise EnhancementError(f"media enhancement failed: {exc}") from exc

    @staticmethod
    def _result(source: Path, target: Path, profile: str, steps: list[str]) -> EnhancementResult:
        if not target.is_file() or target.stat().st_size == 0:
            raise EnhancementError("enhancement produced an empty output")
        return EnhancementResult(
            output_path=target,
            profile=profile,
            steps=steps,
            input_sha256=_sha256(source),
            output_sha256=_sha256(target),
        )

    @staticmethod
    def _copy_result(source: Path, target: Path, profile: str, skipped: str) -> EnhancementResult:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        return EnhancementResult(
            output_path=target,
            profile=profile,
            skipped=[skipped],
            input_sha256=_sha256(source),
            output_sha256=_sha256(target),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duration_budget(path: Path) -> int:
    # Keep the subprocess timeout bounded without adding another probe here.
    try:
        return max(1, min(600, int(path.stat().st_size / 250_000)))
    except OSError:
        return 60
