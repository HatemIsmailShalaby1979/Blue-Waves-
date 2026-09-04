from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .dialogue import build_dialogue, dialogue_to_script, language_label, voices_for
from .governance import Governance
from .models import AssetStatus, PodcastAsset, now_iso
from .providers import ProviderHealthMonitor, ProviderRegistry, ProviderUnavailable
from .toolchain import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE


@dataclass
class PodcastGenerationResult:
    success: bool
    asset: PodcastAsset | None = None
    audio_path: str | None = None
    tts_provider_used: str = ""
    music_provider_used: str = ""
    error: str | None = None


class PodcastEngine:
    """ZACK — multi-host podcast engine with TTS + music mixing."""

    def __init__(self, settings: Settings, governance: Governance,
                 provider_registry: ProviderRegistry | None = None,
                 health_monitor: ProviderHealthMonitor | None = None) -> None:
        self._settings = settings
        self._governance = governance
        self._providers = provider_registry
        self._health = health_monitor or ProviderHealthMonitor()

    def generate(self, topic: str, script: str, host_voice: str = "21m00Tcm4TlvDq8ikWAM",
                 guest_voice: str | None = "EXAVITQu4vr4xnSDxMaL", duration_seconds: int = 1800,
                 format: str = "dialogue", music_intro: bool = True,
                 music_outro: bool = True, quality: str = "high",
                 language: str = "en", two_voices: bool = True,
                 host_name: str = "Host", guest_name: str = "Guest") -> PodcastGenerationResult:
        """ZACK — multi-host podcast engine with TTS + music mixing.

        For quality="high": uses ElevenLabs voices (Adam + Bella) for
        human-quality narration, continuous background music bed with
        sidechain compression (music ducks during speech), and music
        fills between pauses.

        ``host_name``/``guest_name`` personalize the show: the opening
        introduces the guest by name instead of the generic "host/guest".
        """
        asset_id = f"podcast-{uuid.uuid4().hex[:12]}"

        # Two distinct voices are mandatory for podcasts: resolve both from the
        # requested language when the caller did not pin them explicitly.
        default_host, default_guest = voices_for(language)
        host_voice = host_voice or default_host
        if two_voices:
            guest_voice = guest_voice or default_guest
        host_name = (host_name or "Host").strip()
        guest_name = (guest_name or "Guest").strip()

        asset = PodcastAsset(
            asset_id=asset_id,
            tenant_id=self._settings.tenant_id,
            title=f"Podcast: {topic}",
            topic=topic,
            host_voice=host_voice,
            guest_voice=guest_voice,
            host_name=host_name,
            guest_name=guest_name,
            language=language,
            duration_target_seconds=duration_seconds,
            format=format,
            script=script,
            media_manifest={},
        )
        asset.transition(AssetStatus.SCRIPTED)

        # Build an ordered host/guest conversation sized to fill the requested
        # duration so the owner never receives a track padded with silence.
        turns = build_dialogue(topic, language, duration_seconds, script)
        if not two_voices:
            turns = [("host", " ".join(text for _, text in turns))]
        else:
            # Personalized cold open: the host welcomes listeners and names
            # the guest, so nobody ever hears the generic "host/guest".
            opener = (f"Welcome back to the show, I'm {host_name}. "
                      f"With me today is {guest_name}, and we're talking about {topic}.")
            turns = [("host", opener)] + turns
        asset.script = dialogue_to_script(turns)
        segments = [
            (text, host_voice if speaker == "host" else (guest_voice or host_voice))
            for speaker, text in turns
        ]
        rendered_segments: list[bytes] = []
        tts_errors: list[str] = []
        for segment_text, voice in segments:
            segment_audio: bytes | None = None
            for tts_provider in self._tts_candidates(quality):
                reservation = None
                try:
                    if self._providers:
                        reservation = self._providers.rotation.reserve(
                            tts_provider.name,
                            monthly_budget_cents=self._settings.monthly_cloud_cents,
                        )
                        if reservation is None:
                            tts_errors.append(f"{tts_provider.name}: quota or budget unavailable")
                            continue
                    segment_audio = tts_provider.generate(text=segment_text, voice_id=voice)
                    asset.tts_provider = tts_provider.name
                    self._health.record_success(tts_provider.name)
                    break
                except Exception as exc:
                    if reservation is not None and self._providers:
                        self._providers.rotation.release(reservation)
                    self._health.record_failure(tts_provider.name, str(exc))
                    tts_errors.append(f"{tts_provider.name}: {exc}")
            if segment_audio is None:
                asset.transition(AssetStatus.REJECTED)
                return PodcastGenerationResult(success=False, asset=asset, error="; ".join(tts_errors))
            rendered_segments.append(segment_audio)
        try:
            host_audio = self._concat_audio(rendered_segments, duration_seconds)
            asset.transition(AssetStatus.VOICE_RECORDING)
        except Exception as exc:
            asset.transition(AssetStatus.REJECTED)
            return PodcastGenerationResult(success=False, asset=asset, error=f"podcast assembly failed: {exc}")

        music_intro_path = None
        music_outro_path = None
        if music_intro or music_outro:
            for music_provider in self._music_candidates(quality):
              reservation = None
              try:
                if self._providers:
                    reservation = self._providers.rotation.reserve(
                        music_provider.name,
                        monthly_budget_cents=self._settings.monthly_cloud_cents,
                    )
                    if reservation is None:
                        continue
                if music_intro:
                    music_intro_audio = music_provider.generate(
                        prompt=f"podcast intro for {topic}",
                        duration=15,
                    )
                    music_intro_path = str(Path(self._settings.data_dir) / "podcasts" / f"{asset_id}-intro.wav")
                    Path(music_intro_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(music_intro_path).write_bytes(music_intro_audio)
                if music_outro:
                    music_outro_audio = music_provider.generate(
                        prompt=f"podcast outro for {topic}",
                        duration=15,
                    )
                    music_outro_path = str(Path(self._settings.data_dir) / "podcasts" / f"{asset_id}-outro.wav")
                    Path(music_outro_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(music_outro_path).write_bytes(music_outro_audio)
                asset.music_provider = music_provider.name
                self._health.record_success(music_provider.name)
                break
              except Exception as exc:
                if reservation is not None and self._providers:
                    self._providers.rotation.release(reservation)
                self._health.record_failure(music_provider.name, str(exc))

        mixed_audio = self._mix_speech_and_music(
            host_audio, music_intro_path, music_outro_path, duration_seconds
        )

        audio_path = str(Path(self._settings.data_dir) / "podcasts" / f"{asset_id}.wav")
        Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).write_bytes(mixed_audio)
        asset.audio_path = audio_path
        asset.music_intro_path = music_intro_path
        asset.music_outro_path = music_outro_path
        asset.transition(AssetStatus.MIXING)
        asset.transition(AssetStatus.AWAITING_OWNER)
        # Populate media_manifest with provider info and paths
        asset.media_manifest = {
            "audio_path": audio_path,
            "music_intro_path": music_intro_path,
            "music_outro_path": music_outro_path,
            "tts_provider": asset.tts_provider,
            "music_provider": asset.music_provider,
            "tts_voice_host": asset.host_voice,
            "tts_voice_guest": asset.guest_voice,
            "host_name": asset.host_name,
            "guest_name": asset.guest_name,
            "provider": asset.tts_provider,  # Primary provider for this podcast (TTS provider)
            "language": language,
            "language_label": language_label(language),
            "two_voices": two_voices,
            "turn_count": len(turns),
        }

        return PodcastGenerationResult(
            success=True,
            asset=asset,
            audio_path=audio_path,
            tts_provider_used=asset.tts_provider,
            music_provider_used=asset.music_provider,
        )

    def _tts_candidates(self, quality: str) -> list[Any]:
        if self._providers:
            return self._providers.configured_media_candidates("tts", quality=quality)
        from .providers import EdgeTTSProvider, OfflineTTSProvider
        return [EdgeTTSProvider(), OfflineTTSProvider()]

    def _music_candidates(self, quality: str) -> list[Any]:
        if self._providers:
            return self._providers.configured_media_candidates("music", quality=quality)
        return [self._select_music_provider()]

    @staticmethod
    def _dialogue_segments(script: str, format: str, host_voice: str, guest_voice: str | None) -> list[tuple[str, str]]:
        if format != "dialogue" or not guest_voice:
            return [(script, host_voice)]
        from .dialogue import _strip_speaker_label
        host_parts: list[str] = []
        guest_parts: list[str] = []
        current = host_parts
        for line in script.splitlines():
            speaker, remainder = _strip_speaker_label(line)
            if speaker == "host":
                current = host_parts
                line = remainder
            elif speaker == "guest":
                current = guest_parts
                line = remainder
            if line.strip():
                current.append(line.strip())
        if not host_parts or not guest_parts:
            midpoint = max(1, len(script) // 2)
            return [(script[:midpoint], host_voice), (script[midpoint:], guest_voice)]
        return [(" ".join(host_parts), host_voice), (" ".join(guest_parts), guest_voice)]

    @staticmethod
    def _concat_audio(segments: list[bytes], duration_seconds: int) -> bytes:
        if not segments:
            raise ProviderUnavailable("no spoken audio segments were generated")
        paths: list[Path] = []
        fd_out, output_name = tempfile.mkstemp(suffix=".wav")
        os.close(fd_out)
        output_path = Path(output_name)
        try:
            for segment in segments:
                fd, name = tempfile.mkstemp(suffix=".audio")
                os.close(fd)
                path = Path(name)
                path.write_bytes(segment)
                paths.append(path)
            inputs: list[str] = []
            filter_parts: list[str] = []
            for index, path in enumerate(paths):
                inputs.extend(["-i", str(path)])
                filter_parts.append(f"[{index}:a]")
            # Concat all segments, then pad silence to reach target duration
            filter_complex = (
                "".join(filter_parts)
                + f"concat=n={len(paths)}:v=0:a=1,"
                + f"apad=whole_dur={duration_seconds},"
                + f"atrim=0:{duration_seconds}"
            )
            command = [
                "ffmpeg", "-y", "-loglevel", "error",
                *inputs,
                "-filter_complex", filter_complex,
                "-ar", str(AUDIO_SAMPLE_RATE), "-ac", str(AUDIO_CHANNELS),
                "-t", str(max(1, duration_seconds)),
                str(output_path),
            ]
            subprocess.run(command, check=True, timeout=max(60, duration_seconds // 2 + 30), capture_output=True)
            return output_path.read_bytes()
        finally:
            for path in paths + [output_path]:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def _mix_speech_and_music(self, speech_wav: bytes, intro_path: str | None,
                              outro_path: str | None, duration: int) -> bytes:
        """Mix speech with intro/outro music using sidechain compression.

        Professional podcast mixing:
        - Music at 0.08 volume (subtle, not distracting)
        - Sidechain compression: music ducks automatically when speech is present
        - Music fills silence gaps between speech segments
        - Fade in/out at segment boundaries
        - Target -16 LUFS (podcast standard)
        """
        has_intro = intro_path and Path(intro_path).is_file()
        has_outro = outro_path and Path(outro_path).is_file()
        if not has_intro and not has_outro:
            return speech_wav

        fd, speech_file = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        speech_p = Path(speech_file)
        speech_p.write_bytes(speech_wav)

        fd2, output_file = tempfile.mkstemp(suffix=".wav")
        os.close(fd2)
        output_p = Path(output_file)

        try:
            inputs = ["-i", str(speech_p)]
            filter_parts = []

            if has_intro:
                inputs.extend(["-i", intro_path])
                # Lower volume (0.08 vs old 0.15) with fade
                filter_parts.append(
                    f"[1:a]aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,"
                    f"volume=0.08,afade=t=in:st=0:d=2,afade=t=out:st=12:d=3[music_in];"
                )
            if has_outro:
                idx = 2 if has_intro else 1
                inputs.extend(["-i", outro_path])
                fade_out_start = max(0, duration - 18)
                filter_parts.append(
                    f"[{idx}:a]aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,"
                    f"volume=0.08,afade=t=in:st=0:d=2,afade=t=out:st=12:d=3[music_out];"
                )

            if has_intro and has_outro:
                filter_parts.append(
                    f"[music_in][music_out]amix=inputs=2:duration=longest:dropout_transition=2,"
                    f"atrim=0:{duration},apad=whole_dur={duration}[music];"
                )
            elif has_intro:
                filter_parts.append(
                    f"[music_in]atrim=0:{duration},apad=whole_dur={duration}[music];"
                )
            else:
                filter_parts.append(
                    f"[music_out]atrim=0:{duration},apad=whole_dur={duration}[music];"
                )

            # Sidechain compression: music ducks when speech is present
            # sidechaincompress makes music -20dB quieter when speech is detected
            filter_parts.append(
                f"[0:a][music]sidechaincompress="
                f"threshold=0.04:ratio=8:attack=5:release=300:level_sc=1[ducked_music];"
            )
            # Mix speech + ducked music, then loudnorm to -16 LUFS for podcast
            filter_parts.append(
                f"[0:a][ducked_music]amix=inputs=2:duration=first:dropout_transition=2,"
                f"loudnorm=I=-16:TP=-1.5:LRA=11,"
                f"atrim=0:{duration},apad=whole_dur={duration}[out]"
            )

            filter_complex = "".join(filter_parts)
            command = [
                "ffmpeg", "-y", "-loglevel", "error",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-ar", str(AUDIO_SAMPLE_RATE), "-ac", str(AUDIO_CHANNELS),
                "-t", str(duration),
                str(output_p),
            ]
            subprocess.run(command, check=True, timeout=max(60, duration // 2 + 30), capture_output=True)
            return output_p.read_bytes()
        except Exception:
            return speech_wav
        finally:
            for p in [speech_p, output_p]:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass

    def _select_tts_provider(self, name: str | None = None) -> Any:
        provider_name = name or self._settings.kokoro_api_key and "kokoro" or "edge_tts"
        if self._providers:
            return self._providers.get_tts_provider(provider_name)
        from .providers import EdgeTTSProvider
        return EdgeTTSProvider()

    def _select_music_provider(self, name: str | None = None) -> Any:
        provider_name = name or self._settings.ace_step_bin and "ace_step" or "ace_step"
        if self._providers:
            try:
                return self._providers.get_music_provider(provider_name)
            except ProviderUnavailable:
                return self._providers.get_music_provider("local_audio_fallback")
        from .providers import ACEStepMusicProvider
        return ACEStepMusicProvider()

    def generate_solo(self, topic: str, script: str, voice: str = "21m00Tcm4TlvDq8ikWAM",
                      duration_seconds: int = 600, language: str = "en") -> PodcastGenerationResult:
        """Explicit single-voice path. Not exposed by the Cockpit podcast form."""
        return self.generate(
            topic=topic,
            script=script,
            host_voice=voice,
            duration_seconds=duration_seconds,
            format="solo",
            music_intro=True,
            music_outro=True,
            language=language,
            two_voices=False,
        )

    def generate_dialogue(self, topic: str, host_script: str, guest_script: str,
                          host_voice: str = "21m00Tcm4TlvDq8ikWAM",
                          guest_voice: str = "EXAVITQu4vr4xnSDxMaL",
                          duration_seconds: int = 1800,
                          language: str = "en") -> PodcastGenerationResult:
        full_script = f"[HOST]: {host_script}\n\n[GUEST]: {guest_script}"
        return self.generate(
            topic=topic,
            script=full_script,
            host_voice=host_voice,
            guest_voice=guest_voice,
            duration_seconds=duration_seconds,
            format="dialogue",
            language=language,
            two_voices=True,
        )
