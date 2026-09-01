# Blue Waves

Governed, hybrid educational content studio that consumes Helix Codex as an external client.

## What is Blue Waves?

Blue Waves is a multi-format content studio (Videos, Music, Podcasts) governed by an owner-controlled, fail-closed autonomy model. Every external communication requires human approval. No action escapes without consent.

Generated media is persisted locally and appears in the Cockpit content library with an audio/video preview. Approval is blocked when a generated preview is missing or empty, so the owner can inspect content before approving it.

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

The Cockpit also provides playback, approve/reject controls, provider connection settings, YouTube OAuth setup, Suno API credential storage, SHIPO recommendations, audience metric import, and owner-approved KOYOSHU performance memory.

## API

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
│   ├── config.py          # Configuration
│   ├── engines.py         # Research/Script/FactCheck/Production
│   ├── finance.py         # SHIPO cost tracking
│   ├── governance.py      # Policy enforcement
│   ├── hybrid.py          # Hybrid compute router
│   ├── ledger.py          # Append-only audit ledger
│   ├── models.py          # Data models
│   ├── music_engine.py    # Music composition
│   ├── podcast_engine.py  # Podcast production
│   ├── providers.py       # Provider protocols + health
│   ├── quality_gates.py   # Quality assessment
│   ├── queue.py           # Content queue
│   ├── scheduler.py       # Batch scheduling
│   ├── service.py         # HTTP API + Cockpit dashboard
│   └── video_engine.py    # Video generation
├── tests/                 # 50 tests
├── docs/                  # Documentation
└── data/                  # Generated content
```

## Configuration

See `.env.example` for all environment variables.

## License

Private. Internal use only.
