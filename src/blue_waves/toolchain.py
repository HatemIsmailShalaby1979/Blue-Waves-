"""Cross-platform media toolchain helpers.

ffmpeg/ffprobe paths, output audio specification, font discovery and media
probing live here so the render paths stop hardcoding POSIX paths and stop
silently inheriting the narration's 24 kHz mono format.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Delivery spec for every rendered asset. Streaming and YouTube targets expect
# stereo 48 kHz; the previous pipeline inherited 24 kHz mono from the TTS input,
# which band-limited the music bed to 12 kHz.
AUDIO_SAMPLE_RATE = 48000
AUDIO_CHANNELS = 2
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"

# Integrated loudness target for streaming platforms.
LOUDNESS_TARGET = -14.0
TRUE_PEAK_CEILING = -1.5
LOUDNESS_RANGE = 11.0

LOUDNORM_FILTER = (
    f"loudnorm=I={LOUDNESS_TARGET}:TP={TRUE_PEAK_CEILING}:LRA={LOUDNESS_RANGE}"
)

# A 100 ms block quieter than this counts as silence.
SILENCE_NOISE_DB = -50
SILENCE_MIN_BLOCK = 0.1


class ToolchainError(RuntimeError):
    """The local media toolchain is missing or unusable."""


@dataclass(frozen=True)
class Toolchain:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    @classmethod
    def from_settings(cls, settings: Any) -> "Toolchain":
        ffmpeg = getattr(settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"
        ffprobe = getattr(settings, "ffprobe_bin", None) or _sibling(ffmpeg, "ffprobe")
        return cls(ffmpeg=ffmpeg, ffprobe=ffprobe)

    def require(self) -> None:
        """Fail loudly at startup instead of mid-render with a cryptic error."""
        missing = [name for name, binary in (("ffmpeg", self.ffmpeg), ("ffprobe", self.ffprobe))
                   if shutil.which(binary) is None and not Path(binary).is_file()]
        if missing:
            raise ToolchainError(
                f"{', '.join(missing)} not found on PATH. Install ffmpeg, or point "
                f"FFMPEG_BIN / FFPROBE_BIN at the executables."
            )

    def run(self, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(args, check=True, timeout=timeout, capture_output=True)


def _sibling(ffmpeg: str, name: str) -> str:
    """Prefer a probe binary sitting next to the configured ffmpeg."""
    path = Path(ffmpeg)
    candidate = path.with_name(name + path.suffix)
    if candidate.is_file():
        return str(candidate)
    return name


def audio_output_args() -> list[str]:
    """Codec arguments that force the delivery spec onto the output."""
    return ["-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE,
            "-ar", str(AUDIO_SAMPLE_RATE), "-ac", str(AUDIO_CHANNELS)]


def find_font(bold: bool = False) -> str | None:
    """Locate a usable TrueType font on Windows, macOS or Linux.

    The previous implementation hardcoded /usr/share/fonts/truetype/dejavu,
    which never resolves on Windows, so drawtext silently fell back to whatever
    fontconfig offered.
    """
    names = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"] if bold else \
            ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"]
    candidates: list[Path] = []
    for env in ("WINDIR", "SystemRoot"):
        root = _env_path(env)
        if root:
            candidates.append(root / "Fonts")
    candidates += [
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/TTF"),
        Path("/Library/Fonts"),
        Path.home() / ".fonts",
    ]
    for directory in candidates:
        if not directory.is_dir():
            continue
        for name in names:
            match = directory / name
            if match.is_file():
                return str(match)
    return None


def _env_path(name: str) -> Path | None:
    import os

    raw = os.getenv(name)
    return Path(raw) if raw else None


def probe_duration(toolchain: Toolchain, path: Path) -> float:
    """Duration in seconds, or 0.0 when the file cannot be read."""
    try:
        result = subprocess.run(
            [toolchain.ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        return float(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


def probe_media(toolchain: Toolchain, path: Path) -> dict[str, Any]:
    """Structured stream/format facts used by the media quality gate."""
    try:
        result = subprocess.run(
            [toolchain.ffprobe, "-v", "error",
             "-show_entries", "format=duration,bit_rate",
             "-show_entries", "stream=codec_type,codec_name,width,height,channels,sample_rate,r_frame_rate,avg_frame_rate,bit_rate",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        import json

        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "duration": _to_float(fmt.get("duration")),
        "bit_rate": _to_int(fmt.get("bit_rate")),
        "width": _to_int(video.get("width")),
        "height": _to_int(video.get("height")),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "channels": _to_int(audio.get("channels")),
        "sample_rate": _to_int(audio.get("sample_rate")),
        "video_frame_rate": _frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "video_bit_rate": _to_int(video.get("bit_rate")),
        "audio_bit_rate": _to_int(audio.get("bit_rate")),
    }


def measure_silence_ratio(toolchain: Toolchain, path: Path, duration: float | None = None) -> float:
    """Fraction of the asset that is silence, in the range 0.0-1.0.

    Uses ffmpeg's silencedetect on the decoded audio rather than decoding in
    Python, so it works on mp4, mp3 and wav alike.
    """
    if duration is None:
        duration = probe_duration(toolchain, path)
    if duration <= 0:
        return 1.0
    try:
        result = subprocess.run(
            [toolchain.ffmpeg, "-v", "info", "-i", str(path),
             "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_BLOCK}",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=max(60, int(duration * 3)),
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    total = 0.0
    for line in result.stderr.splitlines():
        line = line.strip()
        if "silence_end" in line or ("silence_start" in line and "silence_end" not in line):
            continue
        if "silence_duration" in line:
            try:
                total += float(line.split("silence_duration:")[1].strip())
            except (IndexError, ValueError):
                continue
    # Older ffmpeg builds only emit silence_start/silence_end pairs.
    if total == 0.0 and "silence_start" in result.stderr:
        total = _sum_silence_intervals(result.stderr)
    return min(1.0, max(0.0, total / duration))


def _sum_silence_intervals(stderr: str) -> float:
    import re

    starts: list[float] = []
    ends: list[float] = []
    for line in stderr.splitlines():
        match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if match:
            starts.append(float(match.group(1)))
            continue
        match = re.search(r"silence_end:\s*([0-9.]+)", line)
        if match:
            ends.append(float(match.group(1)))
    total = sum(e - s for s, e in zip(starts, ends) if e > s)
    if len(starts) > len(ends):
        total += 0.0
    return total


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _frame_rate(value: Any) -> float:
    if not value:
        return 0.0
    try:
        if isinstance(value, str) and "/" in value:
            numerator, denominator = value.split("/", 1)
            return float(numerator) / float(denominator)
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
