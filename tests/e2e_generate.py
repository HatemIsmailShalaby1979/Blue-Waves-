#!/usr/bin/env python3
"""E2E generation script: video, music, and podcast via the live cockpit HTTP API."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8420"


def post(path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = Request(BASE_URL + path, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def get(path: str) -> dict:
    req = Request(BASE_URL + path, method="GET")
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def check_health():
    try:
        h = get("/health")
        print(f"[OK] Cockpit running: v{h['version']} tenant={h['tenant_id']}")
        return True
    except Exception as e:
        print(f"[FAIL] Cockpit not reachable: {e}")
        return False


# ── 1. VIDEO: 3-minute software engineering video ──────────────────────────

def generate_video() -> dict:
    print("\n═══════════════════════════════════════════════════════════════")
    print("  GENERATING VIDEO: 3-min Software Engineering (high quality)")
    print("═══════════════════════════════════════════════════════════════")
    payload = {
        "topic": "Software Engineering Best Practices: Clean Code, SOLID Principles, and Modern Development Workflows",
        "prompt": "A professional educational title card for a software engineering course. "
                  "Title: 'Software Engineering Best Practices'. Subtitle: 'Clean Code · SOLID Principles · Modern Workflows'. "
                  "Dark navy gradient background with geometric code symbols. Modern, minimal typography.",
        "duration": 180,
        "quality": "high",
    }
    result = post("/v1/generate/video", payload)
    print(f"  Asset ID  : {result['asset_id']}")
    print(f"  Status    : {result['status']}")
    print(f"  Provider  : {result.get('media_manifest', {}).get('provider', 'unknown')}")
    print(f"  File      : {result.get('media_manifest', {}).get('video_path', 'N/A')}")
    return result


# ── 2. MUSIC: 3-min pop techno track ───────────────────────────────────────

def generate_music() -> dict:
    print("\n═══════════════════════════════════════════════════════════════")
    print("  GENERATING MUSIC: 3-min Pop Techno (energetic, motivational)")
    print("═══════════════════════════════════════════════════════════════")
    lyrics = (
        "[Verse 1]\n"
        "Wake up, the world is changing fast\n"
        "Every second moving, leaving shadows in the past\n"
        "I feel the fire rising up inside\n"
        "No more waiting, time to take the ride\n\n"
        "[Pre-Chorus]\n"
        "We can be the ones who make it right\n"
        "Chasing every dream through the neon light\n\n"
        "[Chorus]\n"
        "Change is coming, can you feel it now?\n"
        "We keep on rising, we won't back down\n"
        "Motivation running through my veins\n"
        "Breaking every chain, dancing in the rain\n\n"
        "[Verse 2]\n"
        "The future's ours if we just believe\n"
        "Every step we take is a victory\n"
        "Hearts are beating louder than the beat\n"
        "Running wild and free, nothing can defeat\n\n"
        "[Chorus]\n"
        "Change is coming, can you feel it now?\n"
        "We keep on rising, we won't back down\n"
        "Motivation running through my veins\n"
        "Breaking every chain, dancing in the rain\n\n"
        "[Bridge]\n"
        "Don't look back, we're heading for the stars\n"
        "Every single scar is a battle scar\n"
        "We're unstoppable, we're unbreakable\n"
        "Together we are inevitable\n\n"
        "[Chorus]\n"
        "Change is coming, can you feel it now?\n"
        "We keep on rising, we won't back down\n"
        "Motivation running through my veins\n"
        "Breaking every chain, dancing in the rain\n\n"
        "[Outro]\n"
        "We are the change, we are the light\n"
        "Shining through the darkness of the night"
    )
    payload = {
        "topic": "Energetic pop techno anthem about change and motivation",
        "genre": "pop",
        "mood": "energetic",
        "duration_seconds": 180,
        "lyrics": lyrics,
        "quality": "high",
    }
    result = post("/v1/generate/music", payload)
    print(f"  Asset ID  : {result['asset_id']}")
    print(f"  Status    : {result['status']}")
    print(f"  Provider  : {result.get('provider', 'unknown')}")
    print(f"  File      : {result.get('audio_path', 'N/A')}")
    return result


# ── 3. PODCAST: 15-min RTA vs WFM dialogue ─────────────────────────────────

def generate_podcast() -> dict:
    print("\n═══════════════════════════════════════════════════════════════")
    print("  GENERATING PODCAST: 15-min RTA vs WFM in a Call Center")
    print("═══════════════════════════════════════════════════════════════")
    script = (
        "[HOST] Welcome to Call Center Decoded, the podcast where we break down the real-world "
        "dynamics of contact centre operations. I'm your host, and today we're diving into a topic "
        "that comes up constantly in the industry: what exactly is the difference between Real-Time "
        "Adherence, or RTA, and Workforce Management, or WFM, in the daily life of a call center? "
        "To help us unpack this, I'm joined by a workforce management specialist with over twelve years "
        "of experience. Welcome to the show.\n\n"
        "[GUEST] Thank you for having me. This is a topic I'm passionate about because the two roles "
        "are so often confused, yet they serve very different purposes in keeping a contact centre running smoothly.\n\n"
        "[HOST] Let's start with the basics. For listeners who might not know, can you explain what "
        "Workforce Management does on a day-to-day basis?\n\n"
        "[GUEST] Absolutely. Workforce Management, or WFM, is really the planning arm. On a typical day, "
        "a WFM analyst is looking at historical data, forecasting call volumes, building schedules, and "
        "managing intraday adjustments. They are responsible for ensuring that the right number of agents "
        "with the right skills are available at the right time. It's very analytical, very forward-looking. "
        "A WFM analyst might spend their morning reviewing last week's service level results, updating the "
        "forecast model for next month, and handling an agent's schedule swap request. They use tools like "
        "NICE, Verint, or Genesys WFM to do all of this.\n\n"
        "[HOST] So WFM is about planning ahead. What about RTA? How is that different?\n\n"
        "[GUEST] Real-Time Adherence is the execution arm. While WFM builds the plan, RTA monitors whether "
        "the plan is actually being followed in real time. An RTA analyst or coordinator is watching the floor "
        "right now. Is agent Sarah on her scheduled break? Is agent Mike supposed to be taking calls but instead "
        "he's in after-call work too long? Is the team hitting their adherence targets? The RTA role is reactive "
        "and immediate. They are the eyes on the floor, ensuring compliance with the schedule.\n\n"
        "[HOST] That's a great distinction. Let's talk about the actual daily workflow. What does a typical "
        "day look like for a WFM analyst versus an RTA coordinator?\n\n"
        "[GUEST] Great question. A WFM analyst's day usually starts before the call center even opens. They "
        "might come in early to review the overnight queue data, check if yesterday's forecast matched reality, "
        "and make any necessary adjustments to today's staffing plan. Then they handle intraday management, "
        "which means responding to unexpected changes, like an agent calling in sick or a sudden spike in "
        "volume. They might also attend capacity planning meetings where they discuss upcoming campaigns, "
        "hiring needs, and training schedules. It's very much a strategic, data-driven role.\n\n"
        "[HOST] And the RTA coordinator?\n\n"
        "[GUEST] The RTA coordinator usually starts their shift when the call center floor goes live. They "
        "pull up the real-time adherence dashboard and monitor every agent against their schedule. If someone "
        "is late from break, they log it. If someone is offline when they should be available, they might page "
        "the team lead. They also handle real-time events like emergency schedule changes, unexpected absences, "
        "and floor support requests. Throughout the day they're communicating with supervisors, providing "
        "adherence reports, and sometimes making small schedule tweaks to keep service levels on track.\n\n"
        "[HOST] So one is looking at the big picture and the other is focused on the immediate moment. "
        "Do these two roles ever clash or overlap?\n\n"
        "[GUEST] They definitely overlap, and that's where the relationship gets interesting. The WFM team "
        "creates the schedule, but the RTA team is the one that tells you whether that schedule is actually "
        "working in practice. If RTA sees consistent adherence problems, that feedback goes back to WFM to "
        "improve future scheduling. For example, if agents are consistently late from their breaks, maybe the "
        "break windows need to be widened. If certain time slots always have too many or too few agents, "
        "the forecast model needs updating. It's a continuous feedback loop.\n\n"
        "[HOST] That feedback loop is crucial. What are the most common metrics each role tracks?\n\n"
        "[GUEST] For WFM, the key metrics are forecast accuracy, schedule efficiency, service level achievement, "
        "and average speed of answer. They're looking at whether the plan delivered the promised results. "
        "For RTA, the primary metric is adherence percentage, which measures how closely agents followed their "
        "assigned schedules. They also track punctuality, break compliance, and availability rates. "
        "Both roles care about occupancy and utilization, but from different angles.\n\n"
        "[HOST] What happens when things go wrong? What's the emergency response for each role?\n\n"
        "[GUEST] When WFM detects a problem, like a forecast miss or a staffing shortage next week, they "
        "activate contingency plans. That might mean pulling in overtime, rescheduling training, or requesting "
        "temp staff. When RTA detects a problem in real time, like a sudden volume spike or multiple absences, "
        "they take immediate action. They might reallocate agents between queues, shorten break windows, or "
        "escalate to operations for floor support. The WFM response is planned; the RTA response is urgent.\n\n"
        "[HOST] Last question: for someone deciding between a career in WFM versus RTA, what should they consider?\n\n"
        "[GUEST] If you love data, forecasting, and long-term strategic planning, WFM is your path. If you "
        "thrive on real-time decision making, people management, and fast-paced environments, RTA is more your "
        "speed. Both roles are essential. Without WFM, you have no plan. Without RTA, the plan falls apart. "
        "The best contact centres treat them as two halves of the same whole.\n\n"
        "[HOST] That's a perfect way to put it. Thank you so much for sharing your expertise today. "
        "To all our listeners, whether you're in WFM, RTA, or just starting your call center career, "
        "remember: the plan and the execution are equally important. Until next time, keep optimizing."
    )
    payload = {
        "topic": "The difference between RTA and WFM daily tasks in a call center",
        "script": script,
        "host_voice": "en-US-GuyNeural",
        "guest_voice": "en-US-JennyNeural",
        "duration_seconds": 900,
        "format": "dialogue",
        "quality": "high",
    }
    result = post("/v1/generate/podcast", payload)
    print(f"  Asset ID    : {result['asset_id']}")
    print(f"  Status      : {result['status']}")
    print(f"  TTS Provider: {result.get('tts_provider', 'unknown')}")
    print(f"  File        : {result.get('audio_path', 'N/A')}")
    return result


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    print("Blue Waves E2E Content Generation")
    print("=" * 60)

    if not check_health():
        return 1

    results = {}

    # Video
    try:
        results["video"] = generate_video()
    except Exception as e:
        print(f"[ERROR] Video generation failed: {e}")
        results["video"] = {"error": str(e)}

    # Music
    try:
        results["music"] = generate_music()
    except Exception as e:
        print(f"[ERROR] Music generation failed: {e}")
        results["music"] = {"error": str(e)}

    # Podcast
    try:
        results["podcast"] = generate_podcast()
    except Exception as e:
        print(f"[ERROR] Podcast generation failed: {e}")
        results["podcast"] = {"error": str(e)}

    # Summary
    print("\n" + "=" * 60)
    print("GENERATION SUMMARY")
    print("=" * 60)
    for kind, result in results.items():
        status = result.get("status", result.get("error", "unknown"))
        asset_id = result.get("asset_id", "N/A")
        print(f"  {kind.upper():10s} | {status:20s} | {asset_id}")

    # Approvals
    print("\nApprovals queue:")
    try:
        approvals = get("/v1/approvals")
        for item in approvals.get("ready_to_publish", []):
            print(f"  READY    : {item['asset_id']} ({item.get('content_type', 'unknown')})")
        for item in approvals.get("retryable", []):
            print(f"  RETRYABLE: {item['asset_id']} ({item.get('content_type', 'unknown')})")
        for item in approvals.get("awaiting_owner", []):
            print(f"  PENDING  : {item['asset_id']} ({item.get('content_type', 'unknown')})")
    except Exception as e:
        print(f"  [WARN] Could not fetch approvals: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
