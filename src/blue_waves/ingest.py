"""External media ingest helpers.

Deterministic, standard-library-only primitives used when an owner-supplied
video file enters the Blue Waves pipeline. Nothing here mutates application
state; the orchestration lives in :class:`blue_waves.application.BlueWavesApplication`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

#: Read size used when streaming a file through SHA-256 (1 MiB).
HASH_CHUNK_SIZE = 1024 * 1024

#: ffprobe binary name; overridable so a deployment can pin a specific build.
FFPROBE_BIN = "ffprobe"

#: Longest edge at or above which a frame is reported as 4K.
_UHD_LONG_EDGE = 3840
_UHD_SHORT_EDGE = 2160
_FHD_SHORT_EDGE = 1080
_HD_SHORT_EDGE = 720


def sha256_file(path: Path, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Return the hex SHA-256 of ``path``, read in ``chunk_size`` blocks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_video_file(path: Path, ffprobe_bin: str = FFPROBE_BIN) -> dict[str, Any] | None:
    """Inspect a video file with ffprobe.

    Returns ``{duration, width, height, video_codec, audio_codec, size_bytes}``
    or ``None`` when the file cannot be read as video. No exception escapes:
    an unreadable, truncated or non-video file is a ``None`` result, not an error.
    """
    target = Path(path)
    try:
        size_bytes = target.stat().st_size
    except OSError:
        return None
    if size_bytes <= 0:
        return None

    command = [
        ffprobe_bin, "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height",
        "-show_entries", "format=duration",
        "-of", "json", str(target),
    ]
    try:
        completed = subprocess.run(command, check=True, timeout=60, capture_output=True, text=True)
        data: dict[str, Any] = json.loads(completed.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None

    streams = data.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video_stream is None:
        return None

    try:
        duration = float(data.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0

    return {
        "duration": duration,
        "width": int(video_stream.get("width", 0) or 0),
        "height": int(video_stream.get("height", 0) or 0),
        "video_codec": str(video_stream.get("codec_name", "") or ""),
        "audio_codec": str((audio_stream or {}).get("codec_name", "") or ""),
        "size_bytes": size_bytes,
    }


def resolution_label(width: int, height: int) -> str:
    """Classify a frame size as ``4k``, ``1080p``, ``720p`` or ``sd``.

    The short edge decides, so vertical and square deliveries classify the same
    way as landscape ones.
    """
    short_edge = min(int(width or 0), int(height or 0))
    long_edge = max(int(width or 0), int(height or 0))
    if short_edge >= _UHD_SHORT_EDGE and long_edge >= _UHD_LONG_EDGE:
        return "4k"
    if short_edge >= _FHD_SHORT_EDGE:
        return "1080p"
    if short_edge >= _HD_SHORT_EDGE:
        return "720p"
    return "sd"
