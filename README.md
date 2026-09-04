# Blue Waves

**Status: Production control plane verified — YouTube publishing and local generation are E2E-tested; revenue remains unproven (see [PRODUCTION_FINANCIAL_EXECUTION_REPORT_2026-09-03.md](PRODUCTION_FINANCIAL_EXECUTION_REPORT_2026-09-03.md)).**

Governed, hybrid educational content studio that consumes Helix Codex as an external client.

## What is Blue Waves?

Blue Waves is a multi-format content studio (Videos, Music, Podcasts) governed by an owner-controlled, fail-closed autonomy model. Every external communication requires human approval. No action escapes without consent.

Generated media is persisted locally and appears in the Cockpit content library with an audio/video preview. The production path now uses quota-aware provider rotation, a FFmpeg-first mastering layer, stronger technical quality proxies, and an asynchronous contract for optional free-GPU jobs. Approval is blocked when a generated preview is missing, empty, or below the quality gate, so the owner can inspect content before approving it. See [docs/ZERO_COST_QUALITY_IMPLEMENTATION.md](docs/ZERO_COST_QUALITY_IMPLEMENTATION.md).

## Current Status (v0.3.0)

| Component | Status | Notes |
|-----------|--------|-------|
| **Video Generation** | ✅ Working | Local (Ken Burns 1080p) + Cloud-ready (Kling/Seedance) + video-use post-production (overlays, captions, grading, YouTube-spec CRF 18) |
| **Music Generation** | ✅ Working | Suno API (3+ min full songs + lyrics) → aimlapi → ACE-Step → local fallback; -14 LUFS mastering |
| **Podcast Generation** | ✅ Working | ElevenLabs TTS (Adam/Bella) → Kokoro → Edge-TTS; sidechain-ducked music beds; -16 LUFS |
| **YouTube OAuth** | ✅ **Complete** | New client ID configured, test user active |
| **YouTube Upload** | ✅ **Verified** | End-to-end pipeline tested |
| **Podcast RSS** | ✅ Working | iTunes-compatible RSS 2.0 |
| **YouTube Analytics** | ✅ Ready | `fetch_youtube_analytics` + `sync_published_metrics` |
| **Scheduler** | ✅ Automated | `tick()` + `run_automated_cycle()`: queue → generate → quality gate → awaiting_owner, retries ×3, ledger-logged |
| **KOYOSHU/SHIPO** | ✅ Active | Metrics → Proposals → Approval → Learning |
| **SHEPO Finance** | ✅ Active | Real per-provider costs, revenue projection (YouTube CPM), break-even, provider ROI (`/api/shepo/*`) |
| **Secrets Encryption** | ✅ Active | AES-256-GCM + master password at rest |
| **Provider Approvals** | ✅ Active | Cloud providers fail closed until owner approves |
| **Monetization** | ✅ Active | Sponsor pipeline + media kit generator |
| **Cockpit Full Board** | ✅ Active | 10 panels: generate, review, crew (+SHEPO), memory, finance, provider health, scheduler, library, connections, publishing; auto-refresh 10s |
| **Quality Gates** | ✅ Real metrics | ffprobe + FFT + LUFS + silence: 1080p/30fps/h264, 48kHz stereo, -14 LUFS music/video, -16 LUFS podcast |
| **Tests** | ✅ Passing | E2E video/music/podcast quality + gate + SHEPO + cockpit + scheduler automation |

> The ✅ marks above reflect **technical** functionality only. They do **not** mean the studio is generating stable income — it remains pre-revenue ($0), per `PROFIT_AUDIT_2026-09-01.md`. Production-scale revenue (and the SaaS-pivot GO/NO-GO) is still an open decision tracked in `DECISIONS.md`.

### Recent Verification (2026-09-03)

- ✅ YouTube OAuth: Complete (client ID: `417279649263-kdbsc08ncvuc2sel78s9fdl3vlu4uri5`, scopes: `youtube.upload`, `yt-analytics.readonly`)
- ✅ End-to-end video publish: Verified (`NHXdNQzF5m0` → `https://www.youtube.com/watch?v=NHXdNQzF5m0`)
- ✅ Podcast RSS: Generating valid iTunes-compatible RSS 2.0
- ✅ 52 tests passing, including a real HTTP cockpit generation/reject/retry/approve/preview test
- ✅ Rejected previews generate owner-approved enhanced attempts with lineage metadata
- ✅ Configured free/developer-tier cloud text providers are orchestrated as a fallback chain
- ✅ Music and podcast uploads are packaged as valid MP4 videos before YouTube upload
- ✅ Local renderers normalized to the delivery spec (stereo 48 kHz); fresh music, podcast, and Ken Burns video each approved with quality score 1.0 via the cockpit API
- ✅ Quality gate verified to block under-spec media (wrong sample rate, padded silence ≥ 40%, low frame rate/bitrate, non-review assets) with structured errors
- ✅ Three-layer zero-cost quality transformation implemented: persisted quota-aware rotation, asynchronous free-GPU job contract, and FFmpeg-first audio/video mastering with provenance hashes

## Quick Start

```bash
# Install
pip install -e ".[server,test]"

# Run tests
python -m pytest tests/ -v

# Start server with Cockpit dashboard
blue-waves cockpit --port 8420

# Open in browser
open http://localhost:8420
```

## Crew Members

| Agent | Role | Tier |
|-------|------|------|
| MIRA | Research & Market Analyst | standard |
| ZACK | Content Writer | external_communication |
| BELAL | Image & Video Producer | external_communication |
| MAYAR | Executive Assistant | standard |
| LEO | Distribution Manager | external_communication |
| JOE | Finance Advisor | advisory_action |
| NELLY | Legal Advisor | catalog_only |
| KOYOSHU | Business Analyst / Metacognition | meta |
| SHEPO | Finance & Profit Strategist | advisory_action |

## Architecture

- **Governance:** Fail-closed policy enforcement. Every publish requires owner approval.
- **Hybrid Compute:** Local-first. Cloud only where quality demands it.
- **Append-Only Ledger:** SHA-256 hash chain. Every action recorded and verifiable.
- **Two-Gate Model:** Gate 1 (topic approval) → Generation → Gate 2 (content approval) → Publish.

## CLI Commands

```bash
blue-waves health          # System health
blue-waves agents          # Crew roster
blue-waves register        # Register with Codex
blue-waves review          # Weekly review
blue-waves demo            # Full demo workflow
blue-waves serve           # HTTP API (port 8787)
blue-waves cockpit         # HTTP API + Cockpit dashboard (port 8420)
```

The Cockpit is now a single-panel owner control board: system health, media library with inline audio/video previewers and approve/reject/retry-with-feedback/publish controls, pending-approval queue, crew member monitoring with a task board, generation forms, finance plan (budget, goal, responsible owners), metacognition (SHIPO + KOYOSHU performance ranking), provider terms approval and API-key entry that is encrypted at rest and never shown again, scheduler stats/tick, and a sponsor/media-kit panel.

### Secrets at rest

Cloud credentials (`api_key`, `access_token`, `refresh_token`, `client_secret`, `oauth_state`) are encrypted with AES-256-GCM and a master password. Set `BLUE_WAVES_MASTER_PASSWORD` in `.env` to enable encryption; without it the cockpit falls back to storing credentials in plaintext as before. See `.env.example`.

## API Examples

```bash
# Health
curl http://localhost:8420/health

# Agents
curl http://localhost:8420/v1/agents

# Create lesson
curl -X POST http://localhost:8420/v1/lessons \
  -H "Content-Type: application/json" \
  -d '{"topic": "How Erlang C works"}'

# Generate music
curl -X POST http://localhost:8420/v1/generate/music \
  -H "Content-Type: application/json" \
  -d '{"topic": "ocean waves", "genre": "ambient", "duration_seconds": 60}'

# Generate podcast
curl -X POST http://localhost:8420/v1/generate/podcast \
  -H "Content-Type: application/json" \
  -d '{"topic": "AI", "script": "Welcome...", "host_voice": "en-GB-SoniaNeural"}'

# Generate video
curl -X POST http://localhost:8420/v1/generate/video \
  -H "Content-Type: application/json" \
  -d '{"topic": "ML basics", "prompt": "Neural network", "duration": 10}'

# Inspect generated content and intelligence
curl http://localhost:8420/v1/music
curl http://localhost:8420/v1/podcasts
curl http://localhost:8420/v1/videos
curl http://localhost:8420/v1/intelligence
```

## Project Structure

```
blue-waves/
├── src/blue_waves/
│   ├── agents.py          # Crew definitions
│   ├── application.py     # Business workflow
│   ├── cli.py             # CLI
│   ├── cockpit_server.py  # Cockpit HTTP handler (port 8420)
│   ├── cockpit_ui.py      # Single-panel cockpit dashboard (HTML/JS)
│   ├── compat.py          # StrEnum backport (Python 3.10)
│   ├── config.py          # Configuration
│   ├── connections.py     # Encrypted credential store
│   ├── crypto.py          # AES-256-GCM secret encryption
│   ├── engines.py         # Research/Script/FactCheck/Production
│   ├── finance.py         # SHIPO cost tracking
│   ├── governance.py      # Policy enforcement
│   ├── hybrid.py          # Hybrid compute router
│   ├── ledger.py          # Append-only audit ledger
│   ├── models.py          # Data models
│   ├── monetization.py    # Sponsor tracker + media kit
│   ├── music_engine.py    # Music composition
│   ├── podcast_engine.py  # Podcast production
│   ├── provider_approvals.py # Cloud provider approval gate
│   ├── providers.py       # Provider protocols + health
│   ├── quality_gates.py   # Quality assessment
│   ├── queue.py           # Content queue
│   ├── scheduler.py       # Batch scheduling
│   ├── service.py         # HTTP API (port 8787)
│   └── video_engine.py    # Video generation
├── tests/                 # 52 tests
├── docs/                  # Documentation
└── data/                  # Generated content
```

## Configuration

See `.env.example` for all environment variables.

## Quality Standards (v0.3.0)

| Media | Spec |
|-------|------|
| Video high/premium | 1920×1080, ≥23fps, h264, ≥2.5 Mbps, stereo 48kHz, -14 LUFS, +faststart |
| Music high/premium | ≥180s, stereo 48kHz, -14 LUFS, full verse/chorus/bridge structure |
| Podcast | stereo 48kHz, -16 LUFS, speech ratio ≥60%, no silence gaps >5s |

## Setup — Quality Sprint providers

```bash
# Suno — full-length AI music (custom lyrics, genre tags, 3+ min)
SUNO_API_KEY=...
SUNO_BASE_URL=https://api.suno.ai/v1

# ElevenLabs — natural TTS voices + Scribe transcription for video-use
ELEVENLABS_API_KEY=...
ELEVENLABS_BASE_URL=https://api.elevenlabs.io/v1

# video-use post-production (vendored under vendor/video_use)
VIDEO_USE_ENABLED=true
VIDEO_USE_SKILL_PATH=vendor/video_use/SKILL.md
```

Key environment variables:
```bash
# Publishing
YOUTUBE_UPLOAD_ENABLED=true
YOUTUBE_OAUTH_CLIENT_ID=...
YOUTUBE_OAUTH_CLIENT_SECRET=...
YOUTUBE_CHANNEL_ID=...

# Cloud Providers (optional)
SUNO_API_KEY=...
ELEVENLABS_API_KEY=...
AIMLAPI_API_KEY=...
KAI_API_KEY=...
KLING_API_KEY=...
SEEDANCE_API_KEY=...
KOKORO_API_KEY=...
GOOGLE_TTS_CREDENTIALS_PATH=...

# Limits
BLUE_WAVES_MONTHLY_CLOUD_CENTS=5000
```

## License

Private. Internal use only.
