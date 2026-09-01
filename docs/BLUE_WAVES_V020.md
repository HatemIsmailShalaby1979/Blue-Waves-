# Blue Waves v0.2.0 — Multi-Format Content Studio

## Overview

Blue Waves is a governed, hybrid educational content studio that consumes Helix Codex as an external client. v0.2.0 expands from video-only to support **Videos, Music, and Podcasts** with the same hybrid orchestration logic, AI crew agents, and governance model.

### Operational correction (0.2.1)

The Cockpit is the owner control plane: generated media is persisted and playable before approval; approve/reject is explicit; provider credentials and connections are configured in the Cockpit; and audience metrics feed owner-approved SHIPO/KOYOSHU recommendations. YouTube uses standard Google OAuth after owner configuration. Suno API credentials are supported, while undocumented consumer-account OAuth is not fabricated.

## Crew Members

| Agent | Role | Tier | Can | Cannot |
|-------|------|------|-----|--------|
| **MIRA** | Research & Market Analyst | standard | propose sourced topics, identify unanswered learner questions | publish, invent trends or sources |
| **ZACK** | Content Writer | external_communication | write AR and EN lessons, preserve uncertainty | publish, make unsupported factual claims |
| **BELAL** | Image & Video Producer | external_communication | plan hybrid media renders, assemble local fallback videos | publish, skip golden-asset checks |
| **MAYAR** | Executive Assistant | standard | compress queues, surface owner decisions | decide for the owner, approve its own summaries |
| **LEO** | Distribution Manager | external_communication | queue approved publication, collect platform metrics | publish without item approval, engagement actions |
| **JOE** | Finance Advisor | advisory_action | track costs, runway and revenue scenarios | move money, promise returns |
| **NELLY** | Legal Advisor | catalog_only | draft checklists and contract questions | give binding legal advice |
| **KOYOSHU** | Business Analyst / Metacognition | meta | propose evidence-backed improvements | apply proposals, review its own governance loop |

## Two-Gate Autonomy Model

**Gate 1 (Topic Approval):**
- MIRA recommends topics via research agents
- Owner reviews/modifies topics before generation
- Generation cannot start without owner approval

**Gate 2 (Content Approval):**
- All finished content (music, podcasts, videos) goes to owner for batch-approve/reject
- Only approved content can be published

## API Endpoints

### Original v0.1.0 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health and governance state |
| GET | `/v1/agents` | Crew member roster |
| POST | `/v1/register` | Register Blue Waves as Codex client |
| POST | `/v1/lessons` | Create bilingual lesson |
| POST | `/v1/assets/{id}/produce` | Produce asset (fact-check + manifest) |
| POST | `/v1/assets/{id}/approve` | Owner approve asset |
| POST | `/v1/assets/{id}/publish` | Publish asset to channel |
| POST | `/v1/assets/{id}/metrics` | Record metric event |
| GET | `/v1/review` | KOYOSHU weekly proposal |

### New v0.2.0 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Cockpit web dashboard |
| GET | `/v1/queue` | Queue status summary |
| GET | `/v1/queue/list` | Full queue list |
| GET | `/v1/finance` | Cost tracking (SHIPO) |
| GET | `/v1/providers/health` | Provider health status |
| GET | `/v1/music` | All music assets |
| GET | `/v1/podcasts` | All podcast assets |
| GET | `/v1/approvals` | Pending owner approvals |
| POST | `/v1/request` | Add content request to queue |
| POST | `/v1/generate/music` | Generate music track |
| POST | `/v1/generate/podcast` | Generate podcast |
| POST | `/v1/generate/video` | Generate video |
| POST | `/v1/approve/music/{id}` | Approve music asset |
| POST | `/v1/approve/podcast/{id}` | Approve podcast asset |
| POST | `/v1/publish/music/{id}` | Publish music asset |
| POST | `/v1/publish/podcast/{id}` | Publish podcast asset |
| GET | `/v1/connections` | Masked provider connection status |
| POST | `/v1/connections` | Save provider credentials locally |
| POST | `/v1/connections/youtube/oauth/start` | Start YouTube OAuth |
| GET | `/oauth/youtube/callback` | Complete YouTube OAuth |
| GET | `/v1/providers/catalog` | Available local/cloud provider catalog |
| GET | `/v1/intelligence` | SHIPO recommendations and KOYOSHU performance evidence |
| POST | `/v1/metrics/{asset_id}` | Import audience metric |
| POST | `/v1/memory/approve` | Owner-approve a performance memory |
| POST | `/v1/reject/{type}/{id}` | Owner-reject generated content |
| GET | `/media/{type}/{id}` | Stream persisted media preview |

## CLI Commands

```bash
blue-waves health          # Show system health
blue-waves agents          # Show crew roster
blue-waves register        # Register with Codex
blue-waves review          # Weekly review proposal
blue-waves demo            # Run full demo workflow
blue-waves serve           # Start HTTP API (port 8787)
blue-waves cockpit         # Start HTTP API + Cockpit dashboard (port 8420)
```

## Configuration

### Environment Variables

```bash
# Tenant
BLUE_WAVES_TENANT_ID=bluewaves
BLUE_WAVES_OWNER_ACTOR=hatem

# Limits
BLUE_WAVES_MAX_WEEKLY_PUBLISHES=5
BLUE_WAVES_MONTHLY_CLOUD_CENTS=0
BLUE_WAVES_MAX_WEEKLY_MUSIC=20
BLUE_WAVES_MAX_WEEKLY_PODCASTS=5
BLUE_WAVES_MAX_WEEKLY_VIDEOS=10

# Local LLM
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=qwen2.5-7b-instruct

# Cloud LLM
OPENROUTER_API_KEY=
GROQ_API_KEY=
NVIDIA_NIM_API_KEY=

# Music providers
SUNO_API_KEY=
ACE_STEP_BIN=

# Video providers
KLING_API_KEY=
SEEDANCE_API_KEY=

# TTS providers
KOKORO_API_KEY=
GOOGLE_TTS_CREDENTIALS_PATH=

# Publishing
YOUTUBE_CHANNEL_ID=
YOUTUBE_UPLOAD_ENABLED=false

# Server
BLUE_WAVES_SERVE_HOST=127.0.0.1
BLUE_WAVES_SERVE_PORT=8787
```

## Usage Examples

### Create Bilingual Lesson
```bash
curl -X POST http://localhost:8420/v1/lessons \
  -H "Content-Type: application/json" \
  -d '{"topic": "How Erlang C turns queue volume into a staffing decision"}'
```

### Generate Music
```bash
curl -X POST http://localhost:8420/v1/generate/music \
  -H "Content-Type: application/json" \
  -d '{"topic": "ocean waves", "genre": "ambient", "mood": "calm", "duration_seconds": 60}'
```

### Generate Podcast
```bash
curl -X POST http://localhost:8420/v1/generate/podcast \
  -H "Content-Type: application/json" \
  -d '{"topic": "AI in education", "script": "Welcome to today episode...", "host_voice": "en-GB-SoniaNeural", "duration_seconds": 600}'
```

### Generate Video
```bash
curl -X POST http://localhost:8420/v1/generate/video \
  -H "Content-Type: application/json" \
  -d '{"topic": "machine learning", "prompt": "Neural network visualization", "duration": 10, "quality": "high"}'
```

### Approve Content
```bash
curl -X POST http://localhost:8420/v1/approve/music/music-happy-pop-001
curl -X POST http://localhost:8420/v1/approve/podcast/podcast-sw-eng-001
```

### Publish Content
```bash
curl -X POST http://localhost:8420/v1/publish/music/music-happy-pop-001 \
  -H "Content-Type: application/json" \
  -d '{"channel": "youtube"}'
```

## Testing

```bash
python -m pytest tests/ -v
```

## Project Structure

```
blue-waves/
├── src/blue_waves/
│   ├── agents.py          # Crew member definitions
│   ├── application.py     # Business workflow
│   ├── cli.py             # CLI interface
│   ├── codex_client.py    # Codex integration
│   ├── config.py          # Configuration
│   ├── engines.py         # Research/Script/FactCheck/Production
│   ├── finance.py         # SHIPO cost tracking
│   ├── governance.py      # Policy enforcement
│   ├── hybrid.py          # Hybrid compute router
│   ├── ledger.py          # Append-only audit ledger
│   ├── models.py          # Data models
│   ├── music_engine.py    # BELAL music composition
│   ├── podcast_engine.py  # ZACK podcast production
│   ├── providers.py       # Provider protocols + health
│   ├── quality_gates.py   # Quality assessment
│   ├── queue.py           # Content queue
│   ├── scheduler.py       # Batch scheduling
│   ├── service.py         # HTTP API + Cockpit dashboard
│   └── video_engine.py    # Video generation
├── tests/                 # Test suite (50 tests)
├── data/                  # Generated content
├── docs/                  # Documentation
├── pyproject.toml
└── .env.example
```
