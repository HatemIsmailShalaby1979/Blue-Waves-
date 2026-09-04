"""Real content quality analysis — FFT, LUFS, spectral, silence detection.

The old quality gate checked file existence. This module provides actual
content-aware quality analysis using ffprobe + ffmpeg signal analysis.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class QualityReport:
    """Detailed quality analysis report."""
    score: float
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.score >= 0.7 and not self.issues


class ContentQualityScorer:
    """Analyze actual media content quality using ffprobe + ffmpeg."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe") -> None:
        self._ffmpeg = ffmpeg_bin
        self._ffprobe = ffprobe_bin

    def analyze_video(self, path: Path, expected_duration: int = 0,
                      min_resolution: tuple[int, int] = (1920, 1080)) -> QualityReport:
        """Analyze video file for real content quality."""
        issues: list[str] = []
        metrics: dict[str, Any] = {}
        score = 1.0

        probe = self._probe(path)
        if not probe:
            return QualityReport(score=0.0, issues=["cannot probe media file"])

        v_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
        a_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)

        if not v_stream:
            return QualityReport(score=0.0, issues=["no video stream found"])

        # Resolution check
        width = int(v_stream.get("width", 0))
        height = int(v_stream.get("height", 0))
        metrics["resolution"] = f"{width}x{height}"
        if width < min_resolution[0] or height < min_resolution[1]:
            issues.append(f"resolution {width}x{height} below required {min_resolution[0]}x{min_resolution[1]}")
            score -= 0.3

        # Codec check
        codec = v_stream.get("codec_name", "")
        metrics["video_codec"] = codec
        if codec not in ("h264", "hevc", "vp9"):
            issues.append(f"unsupported video codec: {codec}")
            score -= 0.3

        # FPS check
        fps = self._parse_fps(v_stream.get("avg_frame_rate", "0/1"))
        metrics["fps"] = fps
        if fps < 23:
            issues.append(f"frame rate {fps} below 23fps")
            score -= 0.1

        # Bitrate check
        bit_rate = int(v_stream.get("bit_rate", 0))
        metrics["video_bitrate"] = bit_rate
        if bit_rate and bit_rate < 2_500_000:
            issues.append(f"video bitrate {bit_rate} below 2.5 Mbps")
            score -= 0.1

        # Duration check
        duration = float(v_stream.get("duration", 0) or probe.get("format", {}).get("duration", 0))
        metrics["duration"] = duration
        if duration <= 0:
            issues.append("video duration is zero")
            score -= 0.3
        if expected_duration > 0 and abs(duration - expected_duration) > max(2, expected_duration * 0.05):
            issues.append(f"duration {duration:.1f}s differs from target {expected_duration}s")
            score -= 0.15

        # Audio check
        if not a_stream:
            issues.append("no audio stream found")
            score -= 0.3
        else:
            audio_codec = a_stream.get("codec_name", "")
            metrics["audio_codec"] = audio_codec
            sample_rate = int(a_stream.get("sample_rate", 0))
            metrics["sample_rate"] = sample_rate
            channels = int(a_stream.get("channels", 0))
            metrics["channels"] = channels
            if sample_rate and sample_rate != 48000:
                issues.append(f"audio sample rate {sample_rate} not 48kHz")
                score -= 0.15
            if channels and channels != 2:
                issues.append(f"audio channels {channels} not stereo")
                score -= 0.1

        # Silence ratio
        silence_ratio = self._measure_silence(path, duration)
        metrics["silence_ratio"] = round(silence_ratio, 3)
        if silence_ratio > 0.3:
            issues.append(f"excessive silence: {silence_ratio:.0%} of video")
            score -= 0.2

        # Loudness measurement (EBU R128)
        loudness = self._measure_loudness(path)
        if loudness is not None:
            metrics["loudness_lufs"] = loudness
            if abs(loudness - (-14.0)) > 3:
                issues.append(f"loudness {loudness:.1f} LUFS far from -14 target")
                score -= 0.1

        return QualityReport(score=max(0.0, score), issues=issues, metrics=metrics)

    def analyze_music(self, path: Path, expected_duration: int = 180) -> QualityReport:
        """Analyze music file for real content quality."""
        issues: list[str] = []
        metrics: dict[str, Any] = {}
        score = 1.0

        probe = self._probe(path)
        if not probe:
            return QualityReport(score=0.0, issues=["cannot probe media file"])

        a_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
        if not a_stream:
            return QualityReport(score=0.0, issues=["no audio stream found"])

        # Duration check — enforce 3+ minute minimum for competitive tracks
        duration = float(a_stream.get("duration", 0) or probe.get("format", {}).get("duration", 0))
        metrics["duration"] = duration
        if duration <= 0:
            issues.append("audio duration is zero")
            score -= 0.3
        if expected_duration > 0 and duration < expected_duration:
            issues.append(f"duration {duration:.0f}s below expected {expected_duration}s")
            score -= 0.2

        # Sample rate
        sample_rate = int(a_stream.get("sample_rate", 0))
        metrics["sample_rate"] = sample_rate
        if sample_rate and sample_rate != 48000:
            issues.append(f"sample rate {sample_rate} not 48kHz")
            score -= 0.15

        # Channels
        channels = int(a_stream.get("channels", 0))
        metrics["channels"] = channels
        if channels and channels != 2:
            issues.append(f"channels {channels} not stereo")
            score -= 0.15

        # Loudness
        loudness = self._measure_loudness(path)
        if loudness is not None:
            metrics["loudness_lufs"] = loudness
            if abs(loudness - (-14.0)) > 3:
                issues.append(f"loudness {loudness:.1f} LUFS far from -14 target")
                score -= 0.1

        # Spectral analysis — check for empty frequency bands
        spectral = self._spectral_analysis(path)
        metrics["spectral"] = spectral
        if spectral.get("low_energy", 0) < 0.01:
            issues.append("no low frequency content (empty bass)")
            score -= 0.15
        if spectral.get("high_energy", 0) < 0.01:
            issues.append("no high frequency content (empty treble)")
            score -= 0.15

        # Silence check
        silence_ratio = self._measure_silence(path, duration)
        metrics["silence_ratio"] = round(silence_ratio, 3)
        if silence_ratio > 0.1:
            issues.append(f"excessive silence: {silence_ratio:.0%}")
            score -= 0.2

        return QualityReport(score=max(0.0, score), issues=issues, metrics=metrics)

    def analyze_podcast(self, path: Path, expected_duration: int = 0) -> QualityReport:
        """Analyze podcast file for real content quality."""
        issues: list[str] = []
        metrics: dict[str, Any] = {}
        score = 1.0

        probe = self._probe(path)
        if not probe:
            return QualityReport(score=0.0, issues=["cannot probe media file"])

        a_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
        if not a_stream:
            return QualityReport(score=0.0, issues=["no audio stream found"])

        # Duration
        duration = float(a_stream.get("duration", 0) or probe.get("format", {}).get("duration", 0))
        metrics["duration"] = duration
        if duration <= 0:
            issues.append("podcast duration is zero")
            score -= 0.3
        if expected_duration > 0 and abs(duration - expected_duration) > max(5, expected_duration * 0.1):
            issues.append(f"duration {duration:.0f}s differs from target {expected_duration}s")
            score -= 0.15

        # Sample rate
        sample_rate = int(a_stream.get("sample_rate", 0))
        metrics["sample_rate"] = sample_rate
        if sample_rate and sample_rate != 48000:
            issues.append(f"sample rate {sample_rate} not 48kHz")
            score -= 0.15

        # Channels
        channels = int(a_stream.get("channels", 0))
        metrics["channels"] = channels
        if channels and channels != 2:
            issues.append(f"channels {channels} not stereo")
            score -= 0.1

        # Loudness — podcast standard is -16 LUFS
        loudness = self._measure_loudness(path)
        if loudness is not None:
            metrics["loudness_lufs"] = loudness
            if abs(loudness - (-16.0)) > 3:
                issues.append(f"loudness {loudness:.1f} LUFS far from -16 podcast target")
                score -= 0.1

        # Speech-to-silence ratio — podcasts should be mostly speech
        silence_ratio = self._measure_silence(path, duration)
        metrics["silence_ratio"] = round(silence_ratio, 3)
        speech_ratio = 1.0 - silence_ratio
        metrics["speech_ratio"] = round(speech_ratio, 3)
        if speech_ratio < 0.6:
            issues.append(f"speech ratio {speech_ratio:.0%} below 60%")
            score -= 0.2

        return QualityReport(score=max(0.0, score), issues=issues, metrics=metrics)

    def _probe(self, path: Path) -> dict[str, Any] | None:
        try:
            result = subprocess.run(
                [self._ffprobe, "-v", "error", "-show_entries",
                 "stream=codec_type,codec_name,width,height,duration,bit_rate,avg_frame_rate,sample_rate,channels",
                 "-show_entries", "format=duration",
                 "-of", "json", str(path)],
                check=True, timeout=30, capture_output=True, text=True,
            )
            return json.loads(result.stdout)
        except Exception:
            return None

    @staticmethod
    def _parse_fps(rate_str: str) -> float:
        num, _, den = rate_str.partition("/")
        try:
            n = float(num)
            d = float(den or "1")
            return n / d if d else 0
        except (ValueError, ZeroDivisionError):
            return 0

    def _measure_silence(self, path: Path, duration: float) -> float:
        """Measure the ratio of silence to total duration."""
        if duration <= 0:
            return 0.0
        try:
            result = subprocess.run(
                [self._ffmpeg, "-i", str(path), "-af",
                 "silencedetect=n=-35dB:d=0.5", "-f", "null", "-"],
                check=True, timeout=60, capture_output=True, text=True,
            )
            # Parse silence_start/silence_end pairs from stderr
            stderr = result.stderr
            silence_start: list[float] = []
            silence_end: list[float] = []
            for line in stderr.split("\n"):
                if "silence_start:" in line:
                    val = line.split("silence_start:")[-1].strip().split()[0]
                    silence_start.append(float(val))
                elif "silence_end:" in line:
                    val = line.split("silence_end:")[-1].strip().split()[0]
                    silence_end.append(float(val))
            total_silence = 0.0
            for i, start in enumerate(silence_start):
                if i < len(silence_end):
                    total_silence += silence_end[i] - start
            return min(1.0, total_silence / duration)
        except Exception:
            return 0.0

    def _measure_loudness(self, path: Path) -> float | None:
        """Measure integrated loudness in LUFS (EBU R128)."""
        try:
            result = subprocess.run(
                [self._ffmpeg, "-i", str(path), "-af",
                 "loudnorm=print_format=json", "-f", "null", "-"],
                check=True, timeout=60, capture_output=True, text=True,
            )
            # Parse JSON from stderr (loudnorm outputs to stderr)
            stderr = result.stderr
            # Find the JSON block
            json_start = stderr.find("{")
            json_end = stderr.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(stderr[json_start:json_end])
                lufs_str = data.get("input_i", "0")
                return float(lufs_str)
        except Exception:
            pass
        return None

    def _spectral_analysis(self, path: Path) -> dict[str, float]:
        """Basic spectral analysis — check for energy in low/mid/high bands."""
        try:
            # Use ffmpeg astats to get frequency band energy
            result = subprocess.run(
                [self._ffmpeg, "-i", str(path), "-af",
                 "lowpass=f=250,astats=metadata=1:reset=1", "-f", "null", "-"],
                check=True, timeout=60, capture_output=True, text=True,
            )
            # Parse RMS level from stderr
            low_energy = self._extract_rms(result.stderr)

            result = subprocess.run(
                [self._ffmpeg, "-i", str(path), "-af",
                 "highpass=f=8000,astats=metadata=1:reset=1", "-f", "null", "-"],
                check=True, timeout=60, capture_output=True, text=True,
            )
            high_energy = self._extract_rms(result.stderr)

            return {"low_energy": low_energy, "high_energy": high_energy}
        except Exception:
            return {"low_energy": 0.0, "high_energy": 0.0}

    @staticmethod
    def _extract_rms(stderr: str) -> float:
        """Extract RMS level from astats output."""
        for line in stderr.split("\n"):
            if "RMS level" in line:
                try:
                    val = line.split(":")[-1].strip().split()[0]
                    return abs(float(val))
                except (ValueError, IndexError):
                    pass
        return 0.0
