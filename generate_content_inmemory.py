#!/usr/bin/env python3
"""Blue Waves v0.2.0 — In-Memory Content Generation Test

Uses in-memory test doubles to demonstrate the full workflow
without requiring external providers or API keys.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / "src"))

from blue_waves.config import Settings
from blue_waves.finance import FinanceEngine
from blue_waves.governance import Governance, Policy
from blue_waves.models import AssetStatus, MusicAsset, PodcastAsset, ContentAsset, now_iso


@dataclass
class InMemoryVideoProvider:
    name: str = "in_memory_video"
    generated: list[dict[str, Any]] = field(default_factory=list)

    def generate(self, prompt: str, duration: int = 5, resolution: str = "720p", **kwargs: Any) -> bytes:
        self.generated.append({"prompt": prompt, "duration": duration, "resolution": resolution})
        return b"fake-video-bytes-12345"


@dataclass
class InMemoryMusicProvider:
    name: str = "in_memory_music"
    generated: list[dict[str, Any]] = field(default_factory=list)

    def generate(self, prompt: str, lyrics: str = "", duration: int = 180,
                 genre: str = "pop", mood: str = "happy", **kwargs: Any) -> bytes:
        self.generated.append({"prompt": prompt, "duration": duration, "genre": genre, "mood": mood})
        return b"fake-wav-audio-bytes-67890"


@dataclass
class InMemoryTTSProvider:
    name: str = "in_memory_tts"
    generated: list[dict[str, Any]] = field(default_factory=list)

    def generate(self, text: str, voice_id: str = "default", **kwargs: Any) -> bytes:
        self.generated.append({"text": text[:100], "voice": voice_id})
        return b"fake-tts-audio-bytes-abcde"


def create_directories() -> None:
    """Create output directories."""
    dirs = ["data/videos", "data/music", "data/podcasts"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
    print("[OK] Created output directories")


def generate_video(in_memory: InMemoryVideoProvider) -> dict:
    """Generate 2-minute video about software engineering."""
    print("\n" + "="*60)
    print("VIDEO GENERATION: Software Engineering (2 minutes)")
    print("="*60)

    prompt = ("A comprehensive overview of software engineering principles, "
              "showing clean code, testing, CI/CD pipelines, and team collaboration. "
              "Modern tech office environment with developers working on multiple screens.")

    video_bytes = in_memory.generate(prompt=prompt, duration=120, resolution="1080p")

    asset_id = f"video-sw-eng-001"
    video_path = f"data/videos/{asset_id}.mp4"
    Path(video_path).write_bytes(video_bytes)

    asset = ContentAsset(
        asset_id=asset_id,
        tenant_id="bluewaves",
        topic="Software Engineering Best Practices",
        pillar="education",
        language="en",
        status=AssetStatus.PRODUCED,
    )
    asset.media_manifest = {"video_path": video_path, "provider": in_memory.name}

    report = {
        "type": "video",
        "asset_id": asset_id,
        "topic": "Software Engineering Best Practices",
        "duration_seconds": 120,
        "resolution": "1080p",
        "provider": in_memory.name,
        "video_path": video_path,
        "file_size_bytes": len(video_bytes),
        "status": "generated",
    }

    print(f"[OK] Video generated successfully")
    print(f"    Asset ID: {asset_id}")
    print(f"    Duration: 120 seconds (2 minutes)")
    print(f"    Resolution: 1080p")
    print(f"    Provider: {in_memory.name}")
    print(f"    Path: {video_path}")
    print(f"    File size: {len(video_bytes)} bytes")

    return report


def generate_podcast(in_memory_tts: InMemoryTTSProvider,
                     in_memory_music: InMemoryMusicProvider) -> dict:
    """Generate 10-minute podcast with UK English male/female voices."""
    print("\n" + "="*60)
    print("PODCAST GENERATION: Software Engineering (10 minutes)")
    print("="*60)

    host_script = """
    Welcome to today's episode of Tech Talk. I'm your host, and today we're 
    diving deep into the fascinating world of software engineering.
    
    Software engineering is more than just writing code. It's about solving 
    complex problems, building scalable systems, and creating applications 
    that impact millions of lives.
    
    Let's start with the fundamentals. Clean code is the foundation of 
    maintainable software. When we write clean code, we make it easier 
    for future developers to understand, modify, and extend our work.
    """

    guest_script = """
    That's absolutely right. And I'd like to add that testing is equally 
    important. Without proper testing, we risk introducing bugs that could 
    cause system failures.
    
    Continuous Integration and Continuous Deployment, or CI/CD, has 
    revolutionized how we deliver software. Teams can now deploy updates 
    multiple times a day with confidence.
    
    The key is to start with unit tests, then integration tests, and 
    finally end-to-end tests. This pyramid approach ensures comprehensive 
    coverage while maintaining fast feedback loops.
    """

    host_audio = in_memory_tts.generate(text=host_script, voice_id="en-GB-SoniaNeural")
    guest_audio = in_memory_tts.generate(text=guest_script, voice_id="en-GB-RyanNeural")

    intro_music = in_memory_music.generate(prompt="podcast intro", duration=30, genre="pop", mood="happy")
    outro_music = in_memory_music.generate(prompt="podcast outro", duration=30, genre="pop", mood="happy")

    asset_id = f"podcast-sw-eng-001"
    audio_path = f"data/podcasts/{asset_id}.wav"
    intro_path = f"data/podcasts/{asset_id}-intro.wav"
    outro_path = f"data/podcasts/{asset_id}-outro.wav"

    Path(audio_path).write_bytes(host_audio + guest_audio)
    Path(intro_path).write_bytes(intro_music)
    Path(outro_path).write_bytes(outro_music)

    asset = PodcastAsset(
        asset_id=asset_id,
        tenant_id="bluewaves",
        title="Software Engineering Best Practices",
        topic="Software Engineering Best Practices",
        host_voice="en-GB-SoniaNeural",
        guest_voice="en-GB-RyanNeural",
        language="en",
        duration_target_seconds=600,
        format="dialogue",
        script=host_script + "\n\n" + guest_script,
        audio_path=audio_path,
        music_intro_path=intro_path,
        music_outro_path=outro_path,
        tts_provider=in_memory_tts.name,
        music_provider=in_memory_music.name,
    )
    asset.transition(AssetStatus.SCRIPTED)
    asset.transition(AssetStatus.VOICE_RECORDING)
    asset.transition(AssetStatus.MIXING)
    asset.transition(AssetStatus.AWAITING_OWNER)

    report = {
        "type": "podcast",
        "asset_id": asset_id,
        "topic": "Software Engineering Best Practices",
        "duration_seconds": 600,
        "format": "dialogue",
        "host_voice": "en-GB-SoniaNeural (UK Female)",
        "guest_voice": "en-GB-RyanNeural (UK Male)",
        "tts_provider": in_memory_tts.name,
        "music_provider": in_memory_music.name,
        "audio_path": audio_path,
        "intro_path": intro_path,
        "outro_path": outro_path,
        "status": "generated",
    }

    print(f"[OK] Podcast generated successfully")
    print(f"    Asset ID: {asset_id}")
    print(f"    Duration: 600 seconds (10 minutes)")
    print(f"    Format: Dialogue (UK English)")
    print(f"    Host: en-GB-SoniaNeural (Female)")
    print(f"    Guest: en-GB-RyanNeural (Male)")
    print(f"    TTS Provider: {in_memory_tts.name}")
    print(f"    Music Provider: {in_memory_music.name}")
    print(f"    Audio Path: {audio_path}")
    print(f"    Intro Music: {intro_path}")
    print(f"    Outro Music: {outro_path}")

    return report


def generate_music(in_memory: InMemoryMusicProvider) -> dict:
    """Generate 60-second pop music track with female vocals, happy vibes."""
    print("\n" + "="*60)
    print("MUSIC GENERATION: Happy Pop Track (60 seconds)")
    print("="*60)

    lyrics = """Verse 1:
Coding through the morning light
Building dreams with all our might
Functions flowing, bugs are few
Software engineering, we love you

Chorus:
Happy vibes in every line
Clean code shining, feeling fine
Ship it fast, ship it right
Software engineering, pure delight"""

    audio_bytes = in_memory.generate(
        prompt="Happy Software Development Vibes",
        lyrics=lyrics,
        duration=60,
        genre="pop",
        mood="happy",
    )

    asset_id = f"music-happy-pop-001"
    audio_path = f"data/music/{asset_id}.wav"
    Path(audio_path).write_bytes(audio_bytes)

    asset = MusicAsset(
        asset_id=asset_id,
        tenant_id="bluewaves",
        title="Happy Software Development Vibes",
        genre="pop",
        mood="happy",
        duration_seconds=60,
        language="en",
        prompt="Happy Software Development Vibes",
        lyrics=lyrics,
        audio_path=audio_path,
        provider=in_memory.name,
        quality="high",
    )
    asset.transition(AssetStatus.COMPOSING)
    asset.transition(AssetStatus.MIXING)
    asset.transition(AssetStatus.AWAITING_OWNER)

    report = {
        "type": "music",
        "asset_id": asset_id,
        "topic": "Happy Software Development Vibes",
        "genre": "pop",
        "mood": "happy",
        "duration_seconds": 60,
        "vocals": "Female",
        "provider": in_memory.name,
        "audio_path": audio_path,
        "lyrics": lyrics,
        "status": "generated",
    }

    print(f"[OK] Music generated successfully")
    print(f"    Asset ID: {asset_id}")
    print(f"    Duration: 60 seconds")
    print(f"    Genre: Pop")
    print(f"    Mood: Happy")
    print(f"    Vocals: Female")
    print(f"    Provider: {in_memory.name}")
    print(f"    Path: {audio_path}")
    print(f"\n    Lyrics preview:")
    for line in lyrics.split('\n')[:6]:
        print(f"      {line}")

    return report


def main() -> None:
    """Main generation workflow."""
    print("="*60)
    print("BLUE WAVES v0.2.0 — IN-MEMORY CONTENT GENERATION TEST")
    print("="*60)

    create_directories()

    in_memory_video = InMemoryVideoProvider()
    in_memory_music = InMemoryMusicProvider()
    in_memory_tts = InMemoryTTSProvider()

    reports = []

    video_report = generate_video(in_memory_video)
    reports.append(video_report)

    podcast_report = generate_podcast(in_memory_tts, in_memory_music)
    reports.append(podcast_report)

    music_report = generate_music(in_memory_music)
    reports.append(music_report)

    report_path = Path("data/generation_report.json")
    with open(report_path, "w") as f:
        json.dump(reports, f, indent=2)

    print("\n" + "="*60)
    print("GENERATION COMPLETE")
    print("="*60)

    print(f"\n[OK] All content generated successfully")
    print(f"\nReports saved to: {report_path}")

    print(f"\n{'='*60}")
    print("GENERATED FILES LOCATION")
    print(f"{'='*60}")
    print(f"\n  Videos:")
    print(f"    data/videos/video-sw-eng-001.mp4")
    print(f"\n  Podcasts:")
    print(f"    data/podcasts/podcast-sw-eng-001.wav")
    print(f"    data/podcasts/podcast-sw-eng-001-intro.wav")
    print(f"    data/podcasts/podcast-sw-eng-001-outro.wav")
    print(f"\n  Music:")
    print(f"    data/music/music-happy-pop-001.wav")

    print(f"\n{'='*60}")
    print("NEXT STEPS")
    print(f"{'='*60}")
    print(f"\n1. Run the Cockpit UI:")
    print(f"   python3 -m blue_waves.cli cockpit --port 8420")
    print(f"\n2. Open browser to:")
    print(f"   http://localhost:8420")
    print(f"\n3. Approve content in Cockpit before publishing")


if __name__ == "__main__":
    main()
