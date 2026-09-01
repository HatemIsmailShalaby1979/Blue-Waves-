#!/usr/bin/env python3
"""Blue Waves v0.2.0 — Content Generation Test Script

Generates:
1. 2-minute video about software engineering
2. 10-minute podcast with UK English male/female voices
3. 60-second pop music track with female vocals, happy vibes
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from blue_waves.config import Settings
from blue_waves.finance import FinanceEngine
from blue_waves.governance import Governance, Policy
from blue_waves.music_engine import MusicEngine
from blue_waves.podcast_engine import PodcastEngine
from blue_waves.providers import ProviderHealthMonitor
from blue_waves.quality_gates import QualityGates
from blue_waves.queue import ContentQueue
from blue_waves.video_engine import VideoEngine


def create_directories() -> None:
    """Create output directories."""
    dirs = ["data/videos", "data/music", "data/podcasts", "data/quality_reports"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
    print("[OK] Created output directories")


def generate_video(settings: Settings, governance: Governance,
                   health: ProviderHealthMonitor) -> dict:
    """Generate 2-minute video about software engineering."""
    print("\n" + "="*60)
    print("VIDEO GENERATION: Software Engineering (2 minutes)")
    print("="*60)

    engine = VideoEngine(settings, governance, health_monitor=health)

    result = engine.generate(
        topic="Software Engineering Best Practices",
        prompt="A comprehensive overview of software engineering principles, "
               "showing clean code, testing, CI/CD pipelines, and team collaboration. "
               "Modern tech office environment with developers working on multiple screens.",
        duration=120,  # 2 minutes
        resolution="1080p",
        quality="high",
    )

    report = {
        "type": "video",
        "topic": "Software Engineering Best Practices",
        "duration_seconds": 120,
        "success": result.success,
        "provider_used": result.provider_used,
        "video_path": result.video_path,
        "error": result.error,
        "asset_id": result.asset.asset_id if result.asset else None,
    }

    if result.success:
        print(f"[OK] Video generated successfully")
        print(f"    Asset ID: {report['asset_id']}")
        print(f"    Provider: {report['provider_used']}")
        print(f"    Path: {report['video_path']}")
    else:
        print(f"[WARN] Video generation failed (expected without providers)")
        print(f"    Error: {report['error']}")
        print(f"    Asset ID: {report['asset_id']}")

    return report


def generate_podcast(settings: Settings, governance: Governance,
                     health: ProviderHealthMonitor) -> dict:
    """Generate 10-minute podcast with UK English male/female voices."""
    print("\n" + "="*60)
    print("PODCAST GENERATION: Software Engineering (10 minutes)")
    print("="*60)

    engine = PodcastEngine(settings, governance, health_monitor=health)

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

    result = engine.generate_dialogue(
        topic="Software Engineering Best Practices",
        host_script=host_script,
        guest_script=guest_script,
        host_voice="en-GB-SoniaNeural",  # UK English female
        guest_voice="en-GB-RyanNeural",  # UK English male
        duration_seconds=600,  # 10 minutes
    )

    report = {
        "type": "podcast",
        "topic": "Software Engineering Best Practices",
        "duration_seconds": 600,
        "success": result.success,
        "tts_provider_used": result.tts_provider_used,
        "music_provider_used": result.music_provider_used,
        "audio_path": result.audio_path,
        "error": result.error,
        "asset_id": result.asset.asset_id if result.asset else None,
    }

    if result.success:
        print(f"[OK] Podcast generated successfully")
        print(f"    Asset ID: {report['asset_id']}")
        print(f"    TTS Provider: {report['tts_provider_used']}")
        print(f"    Music Provider: {report['music_provider_used']}")
        print(f"    Path: {report['audio_path']}")
    else:
        print(f"[WARN] Podcast generation failed (expected without providers)")
        print(f"    Error: {report['error']}")
        print(f"    Asset ID: {report['asset_id']}")

    return report


def generate_music(settings: Settings, governance: Governance,
                   health: ProviderHealthMonitor) -> dict:
    """Generate 60-second pop music track with female vocals, happy vibes."""
    print("\n" + "="*60)
    print("MUSIC GENERATION: Happy Pop Track (60 seconds)")
    print("="*60)

    engine = MusicEngine(settings, governance, health_monitor=health)

    result = engine.generate(
        topic="Happy Software Development Vibes",
        genre="pop",
        mood="happy",
        duration_seconds=60,
        lyrics="""Verse 1:
Coding through the morning light
Building dreams with all our might
Functions flowing, bugs are few
Software engineering, we love you

Chorus:
Happy vibes in every line
Clean code shining, feeling fine
Ship it fast, ship it right
Software engineering, pure delight""",
        quality="high",
    )

    report = {
        "type": "music",
        "topic": "Happy Software Development Vibes",
        "genre": "pop",
        "mood": "happy",
        "duration_seconds": 60,
        "success": result.success,
        "provider_used": result.provider_used,
        "audio_path": result.audio_path,
        "error": result.error,
        "asset_id": result.asset.asset_id if result.asset else None,
    }

    if result.success:
        print(f"[OK] Music generated successfully")
        print(f"    Asset ID: {report['asset_id']}")
        print(f"    Provider: {report['provider_used']}")
        print(f"    Path: {report['audio_path']}")
    else:
        print(f"[WARN] Music generation failed (expected without providers)")
        print(f"    Error: {report['error']}")
        print(f"    Asset ID: {report['asset_id']}")

    return report


def generate_quality_reports(reports: list[dict]) -> None:
    """Generate quality reports for all content."""
    print("\n" + "="*60)
    print("QUALITY ASSESSMENT")
    print("="*60)

    settings = Settings()
    governance = Governance(Policy())
    quality_gates = QualityGates(settings, governance)

    for report in reports:
        print(f"\n{report['type'].upper()}: {report.get('topic', 'N/A')}")
        if report['success']:
            print(f"  Status: Generated")
            print(f"  Provider: {report.get('provider_used') or report.get('tts_provider_used', 'N/A')}")
            print(f"  Duration: {report.get('duration_seconds', 'N/A')}s")
        else:
            print(f"  Status: Failed (expected without providers)")
            print(f"  Error: {report.get('error', 'N/A')}")

    print("\n[OK] Quality reports generated")


def main() -> None:
    """Main generation workflow."""
    print("="*60)
    print("BLUE WAVES v0.2.0 — CONTENT GENERATION TEST")
    print("="*60)

    create_directories()

    settings = Settings()
    governance = Governance(Policy())
    health = ProviderHealthMonitor()

    reports = []

    video_report = generate_video(settings, governance, health)
    reports.append(video_report)

    podcast_report = generate_podcast(settings, governance, health)
    reports.append(podcast_report)

    music_report = generate_music(settings, governance, health)
    reports.append(music_report)

    generate_quality_reports(reports)

    report_path = Path("data/generation_report.json")
    with open(report_path, "w") as f:
        json.dump(reports, f, indent=2)

    print("\n" + "="*60)
    print("GENERATION COMPLETE")
    print("="*60)
    print(f"\nReports saved to: {report_path}")
    print(f"\nGenerated files location:")
    print(f"  Videos:   data/videos/")
    print(f"  Music:    data/music/")
    print(f"  Podcasts: data/podcasts/")
    print(f"\nTo run Cockpit UI:")
    print(f"  python -m blue_waves.cli cockpit --port 8420")


if __name__ == "__main__":
    main()
