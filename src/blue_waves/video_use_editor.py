"""video-use pipeline integration for Blue Waves.

Integrates the video-use conversation-driven video editor:
    Transcribe -> Pack -> LLM Reasons -> EDL -> Render -> Self-Eval

This module wraps the vendored video-use helpers to provide a clean
interface for the VideoEngine to call during post-production.

The key insight from video-use: instead of processing 45M tokens of raw
frames, it works with a 12KB transcript + on-demand PNGs. This makes
LLM-reasoned editing tractable even on modest hardware.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .toolchain import Toolchain, AUDIO_SAMPLE_RATE, LOUDNORM_FILTER, audio_output_args, find_font


@dataclass
class EditResult:
    """Result of a video-use post-production edit."""
    success: bool
    output_path: Path | None = None
    transcript: str = ""
    edl: list[dict[str, Any]] = field(default_factory=list)
    self_eval_score: float = 0.0
    issues: list[str] = field(default_factory=list)
    error: str | None = None


class VideoUseEditor:
    """Integrates video-use pipeline for professional video post-production.

    Pipeline:
    1. Transcribe narration audio with ElevenLabs Scribe (word-level timestamps)
    2. Pack transcript into compact format
    3. LLM reasons about edit decisions (cut points, b-roll, captions)
    4. Generate EDL (Edit Decision List) with timecodes
    5. Render via ffmpeg: apply cuts, overlays, transitions, color grading
    6. Self-evaluate: check output meets YouTube spec
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._toolchain = Toolchain.from_settings(settings)
        self._elevenlabs_key = getattr(settings, "elevenlabs_api_key", None)
        self._elevenlabs_base = getattr(settings, "elevenlabs_base_url", "https://api.elevenlabs.io/v1")

    def edit(self, raw_video_path: Path, transcript_text: str,
             narration_audio_path: Path | None = None,
             topic: str = "", duration: int = 180,
             width: int = 1920, height: int = 1080) -> EditResult:
        """Run the full video-use post-production pipeline on a raw video.

        Args:
            raw_video_path: Path to the raw video file (from KenBurns or cloud provider)
            transcript_text: The narration script text
            narration_audio_path: Path to the narration audio (for transcription)
            topic: Topic/title for overlays
            duration: Target duration in seconds
            width: Output width
            height: Output height

        Returns:
            EditResult with the edited video path and metadata
        """
        if not raw_video_path or not raw_video_path.exists():
            return EditResult(success=False, error=f"raw video not found: {raw_video_path}")

        issues: list[str] = []
        edl: list[dict[str, Any]] = []
        transcript = transcript_text

        # Step 1: Transcribe narration with ElevenLabs Scribe (if available)
        if narration_audio_path and narration_audio_path.exists() and self._elevenlabs_key:
            try:
                scribe_result = self._transcribe_with_scribe(narration_audio_path)
                if scribe_result:
                    transcript = scribe_result.get("text", transcript)
                    # Build EDL from word-level timestamps
                    edl = self._build_edl_from_transcript(scribe_result, duration)
            except Exception as exc:
                issues.append(f"scribe transcription failed: {exc}")
                # Fall through to text-based EDL
                edl = self._build_text_edl(transcript, duration)
        else:
            # No Scribe available — build EDL from text segmentation
            edl = self._build_text_edl(transcript, duration)

        # Step 2: Pack transcript (compact format for LLM reasoning)
        packed = self._pack_transcript(transcript, edl)

        # Step 3: LLM reasons about edit decisions (if text provider available)
        edit_decisions = self._reason_about_edit(packed, topic, duration)
        if edit_decisions:
            # Merge LLM decisions into EDL
            edl = self._merge_decisions(edl, edit_decisions)

        # Step 4: Render — apply EDL with ffmpeg (overlays, transitions, grading)
        try:
            output_path = self._render_edl(raw_video_path, edl, topic, duration, width, height)
        except Exception as exc:
            return EditResult(
                success=False,
                transcript=transcript,
                edl=edl,
                issues=issues,
                error=f"render failed: {exc}",
            )

        # Step 5: Self-evaluate — check output meets YouTube spec
        score, eval_issues = self._self_evaluate(output_path, duration, width, height)
        issues.extend(eval_issues)

        return EditResult(
            success=True,
            output_path=output_path,
            transcript=transcript,
            edl=edl,
            self_eval_score=score,
            issues=issues,
        )

    def _transcribe_with_scribe(self, audio_path: Path) -> dict[str, Any] | None:
        """Transcribe audio using ElevenLabs Scribe API.

        Returns word-level timestamps + diarization.
        """
        import urllib.request
        import urllib.error

        if not self._elevenlabs_key:
            return None

        # Read audio file
        audio_bytes = audio_path.read_bytes()

        # Create multipart form data
        boundary = "----BlueWavesBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode() + audio_bytes + f"\r\n--{boundary}\r\n".encode()

        req = urllib.request.Request(
            f"{self._elevenlabs_base}/speech-to-text",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "xi-api-key": self._elevenlabs_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                return raw
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _build_edl_from_transcript(scribe_result: dict[str, Any], duration: int) -> list[dict[str, Any]]:
        """Build an Edit Decision List from word-level transcript timestamps.

        Each EDL entry has: start, end, text, type (segment/caption/b-roll)
        """
        edl: list[dict[str, Any]] = []
        words = scribe_result.get("words", [])
        if not words:
            # Fallback: use segments if available
            segments = scribe_result.get("segments", [])
            for seg in segments:
                edl.append({
                    "start": float(seg.get("start", 0)),
                    "end": float(seg.get("end", duration)),
                    "text": seg.get("text", "").strip(),
                    "type": "segment",
                })
            return edl

        # Group words into caption-sized chunks (~5-7 words)
        chunk_size = 6
        current_chunk: list[dict] = []
        for word in words:
            current_chunk.append(word)
            if len(current_chunk) >= chunk_size:
                start = float(current_chunk[0].get("start", 0))
                end = float(current_chunk[-1].get("end", start + 2))
                text = " ".join(w.get("text", "") for w in current_chunk)
                edl.append({"start": start, "end": end, "text": text, "type": "caption"})
                current_chunk = []
        # Flush remaining
        if current_chunk:
            start = float(current_chunk[0].get("start", 0))
            end = float(current_chunk[-1].get("end", duration))
            text = " ".join(w.get("text", "") for w in current_chunk)
            edl.append({"start": start, "end": end, "text": text, "type": "caption"})
        return edl

    @staticmethod
    def _build_text_edl(transcript: str, duration: int) -> list[dict[str, Any]]:
        """Build an EDL from plain text by segmenting into time-coded chunks.

        Used when Scribe transcription is not available — divides the
        transcript evenly across the video duration.
        """
        sentences = [s.strip() for s in transcript.replace("\n", " ").split(".") if s.strip()]
        if not sentences:
            return [{"start": 0, "end": duration, "text": "", "type": "segment"}]

        total_chars = sum(len(s) for s in sentences)
        if total_chars == 0:
            return [{"start": 0, "end": duration, "text": "", "type": "segment"}]

        edl: list[dict[str, Any]] = []
        current_time = 0.0
        for sentence in sentences:
            # Proportional time allocation based on text length
            seg_duration = (len(sentence) / total_chars) * duration
            edl.append({
                "start": current_time,
                "end": current_time + seg_duration,
                "text": sentence + ".",
                "type": "caption",
            })
            current_time += seg_duration
        # Ensure last segment reaches the end
        if edl:
            edl[-1]["end"] = duration
        return edl

    @staticmethod
    def _pack_transcript(transcript: str, edl: list[dict[str, Any]]) -> str:
        """Pack transcript + EDL into a compact format for LLM reasoning.

        The video-use approach: 12KB of text + on-demand PNGs, not 45M tokens
        of raw frames. This makes LM-reasoned editing tractable.
        """
        # Truncate transcript to ~4KB for LLM context
        text = transcript[:4000]
        # Compact EDL: one line per entry
        edl_lines = []
        for entry in edl[:50]:  # Cap at 50 entries
            edl_lines.append(f"[{entry['start']:.1f}-{entry['end']:.1f}] {entry['text'][:80]}")
        edl_compact = "\n".join(edl_lines)
        return f"TRANSCRIPT:\n{text}\n\nEDL:\n{edl_compact}"

    def _reason_about_edit(self, packed: str, topic: str, duration: int) -> list[dict[str, Any]]:
        """Use LLM to reason about edit decisions.

        Asks the LLM: given this transcript and EDL, what improvements should
        we make? Cut points, b-roll suggestions, caption emphasis, transitions.
        """
        # This is a no-op if no text provider is available
        # In production, this would call the configured LLM with a prompt like:
        # "You are a video editor. Given this transcript and EDL, suggest:
        #  1. Cut points for dead air
        #  2. B-roll suggestions for key moments
        #  3. Caption emphasis (which words to highlight)
        #  4. Transition types between segments"
        # For now, return empty decisions — the EDL from transcription is sufficient
        return []

    @staticmethod
    def _merge_decisions(edl: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge LLM edit decisions into the EDL."""
        # Placeholder for future LLM-driven editing
        return edl

    def _render_edl(self, raw_video_path: Path, edl: list[dict[str, Any]],
                    topic: str, duration: int, width: int, height: int) -> Path:
        """Render the final video applying the EDL with ffmpeg.

        Applies:
        - Title overlay at the start
        - Caption text synchronized to EDL entries
        - Color grading (cinematic LUT-style)
        - Fade in/out transitions
        - YouTube delivery spec: H.264 CRF 18, preset slow, 48kHz AAC, -14 LUFS
        """
        fd, output_path_str = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        output_path = Path(output_path_str)

        font = find_font(bold=True)

        def _escape(value: str) -> str:
            return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

        # Build caption filter — progressive drawtext synced to EDL
        caption_filters: list[str] = []
        for i, entry in enumerate(edl[:20]):  # Cap at 20 captions to avoid filter overflow
            text = entry.get("text", "").strip()
            if not text:
                continue
            start = entry.get("start", 0)
            end = entry.get("end", start + 2)
            # Show caption between start and end with fade
            caption_filters.append(
                f"drawtext=fontfile='{_escape(font) if font else ''}':"
                f"text='{_escape(text[:60])}':"
                f"fontsize={int(height * 0.045)}:fontcolor=white:borderw=2:bordercolor=black@0.5:"
                f"x=(w-text_w)/2:y=h-th-60:"
                f"enable='between(t,{start:.1f},{end:.1f})'"
            )

        # Title overlay (first 5 seconds)
        title_text = topic[:50] if topic else ""
        title_filter = (
            f"drawtext=fontfile='{_escape(font) if font else ''}':"
            f"text='{_escape(title_text)}':"
            f"fontsize={int(height * 0.06)}:fontcolor=white:borderw=3:bordercolor=black@0.7:"
            f"x=(w-text_w)/2:y=h*0.15:"
            f"enable='between(t,0,5)'"
        )

        # Color grading: cinematic curve + saturation boost
        grade_filter = "eq=contrast=1.05:brightness=0.02:saturation=1.15:gamma=0.98"

        # Fade in/out
        fade_filter = f"fade=t=in:st=0:d=1.5,fade=t=out:st={max(0, duration - 1.5)}:d=1.5"

        # Combine all video filters
        vf_parts = [title_filter]
        vf_parts.extend(caption_filters)
        vf_parts.append(grade_filter)
        vf_parts.append(fade_filter)
        # Scale to target resolution
        vf_parts.append(f"scale={width}:{height}:flags=lanczos,format=yuv420p")

        vf = ",".join(vf_parts)

        # Audio: loudnorm to -14 LUFS for YouTube
        af = f"aresample={AUDIO_SAMPLE_RATE}:resampler=soxr,{LOUDNORM_FILTER}"

        command = [
            self._toolchain.ffmpeg, "-y", "-loglevel", "error",
            "-i", str(raw_video_path),
            "-vf", vf,
            "-af", af,
            "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-profile:v", "high", "-level", "4.2",
            "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-t", str(duration),
            str(output_path),
        ]

        subprocess.run(command, check=True, timeout=max(120, duration * 3 + 60), capture_output=True)
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("video-use render produced empty output")
        return output_path

    @staticmethod
    def _self_evaluate(output_path: Path, duration: int, width: int, height: int) -> tuple[float, list[str]]:
        """Self-evaluate the rendered output against YouTube spec.

        Returns (score, issues) where score is 0.0-1.0.
        """
        score = 1.0
        issues: list[str] = []

        try:
            import json as _json
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=width,height,codec_name,duration,bit_rate",
                 "-of", "json", str(output_path)],
                check=True, timeout=30, capture_output=True, text=True,
            )
            data = _json.loads(probe.stdout)
            streams = data.get("streams", [])

            # Check video stream
            v_stream = next((s for s in streams if s.get("codec_name") in ("h264", "hevc")), None)
            if not v_stream:
                issues.append("no video stream found")
                score -= 0.5
            else:
                if int(v_stream.get("width", 0)) < width or int(v_stream.get("height", 0)) < height:
                    issues.append(f"resolution below target: {v_stream.get('width')}x{v_stream.get('height')}")
                    score -= 0.2

            # Check audio stream
            a_stream = next((s for s in streams if "audio" in s.get("codec_name", "")), None)
            if not a_stream:
                issues.append("no audio stream found")
                score -= 0.3

            # Check duration
            total_duration = float(v_stream.get("duration", 0) if v_stream else 0)
            if total_duration > 0 and abs(total_duration - duration) > max(2, duration * 0.05):
                issues.append(f"duration {total_duration:.1f}s differs from target {duration}s")
                score -= 0.1

        except Exception as exc:
            issues.append(f"self-eval probe failed: {exc}")
            score -= 0.2

        return max(0.0, score), issues
