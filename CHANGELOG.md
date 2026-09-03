# Changelog

All notable changes to Blue Waves will be documented in this file.

## [0.2.1] - 2026-09-02

### Fixed
- YouTube OAuth: New client ID configured (`417279649263-kdbsc08ncvuc2sel78s9fdl3vlu4uri5`), test user added (`hatemismail2011@gmail.com`), end-to-end verified
- YouTube Upload: End-to-end verified (video `NHXdNQzF5m0` → `https://www.youtube.com/watch?v=NHXdNQzF5m0`)
- Video Engine: Fixed `language` field to use `Language.EN` enum instead of string
- OAuth Callback: Added proper error handling with try/except for graceful failures
- Config Loading: Fixed `.env` loading path resolution (3 levels up from config.py)

### Added
- Podcast RSS: iTunes-compatible RSS 2.0 feed generation (`generate_podcast_rss`)
- YouTube Analytics: `fetch_youtube_analytics` + `sync_published_metrics` methods
- Scheduler: Recurring schedule support (Mon/Wed/Fri default), weekly publish caps
- Video Shorts: `create_short` + `create_shorts_from_longform` for YouTube Shorts automation
- SEO Metadata: Auto-generated titles, descriptions, tags for YouTube uploads
- Shorts Module: New `src/blue_waves/shorts.py` module for short-form video creation

### Changed
- Config: Added `youtube_oauth_client_id` and `youtube_oauth_client_secret` fields
- Config: Added python-dotenv dependency for reliable `.env` loading
- Video Engine: Language field now uses `Language.EN` enum
- Auth: Cleared old connection store, restarted with clean OAuth state

### Security
- SSRF protection: `_validate_url` with allowlists for all external HTTP requests
- Command injection prevention: Input validation + subprocess parameter lists (no shell=True)
- OAuth state validation: Proper state parameter handling in callback

### Verified (2026-09-02)
- YouTube OAuth: Complete (new client ID, test user active, scopes: `youtube.upload`, `yt-analytics.readonly`)
- End-to-end video publish: Verified (`NHXdNQzF5m0` → `https://www.youtube.com/watch?v=NHXdNQzF5m0`)
- Podcast RSS: Valid iTunes-compatible RSS 2.0 with enclosures
- All 50 tests passing

## [0.2.1] - 2026-09-01

### Fixed
- Added playable previews in the generated-content library and approval queue.
- Blocked approval when generated media is missing or empty.
- Added working owner rejection for music, podcasts, and videos.
- Added persisted provider connection metadata and masked credential status.
- Added YouTube OAuth setup/callback plumbing and provider catalog visibility.
- Added audience metric import, SHIPO performance recommendations, and owner-approved KOYOSHU memory proposals.

### Integration notes
- YouTube OAuth requires Google OAuth credentials and YouTube Data API activation.
- Suno API credentials are supported; undocumented consumer-account OAuth is not automated.
- Unconfigured cloud providers fail closed and use local fallbacks where available.

## [0.2.0] - 2026-09-01

### Added
- **Music Engine (BELAL):** ACE-Step (local ROCm) and Suno API (cloud) music generation
- **Podcast Engine (ZACK):** Multi-host dialogue with Kokoro, Edge-TTS, and Google TTS providers
- **Video Engine:** Ken Burns (free), Seedance (paid), and Kling (paid) video generation
- **Finance Engine (SHIPO):** Cost tracking, free-tier maximization, provider cost recommendations
- **Provider Health Monitor:** Sliding window health tracking with automatic fallback
- **Content Queue:** Multi-format queue with priority ordering and batch processing
- **Scheduler:** Autonomous batch scheduling with time windows
- **Quality Gates:** Auto-approve/reject based on quality score thresholds
- **Cockpit Dashboard:** Web UI at `/` showing system health, queue, finance, providers, crew, approvals, and content generation forms
- **Two-Gate Governance Model:** Gate 1 (topic approval) + Gate 2 (content approval)
- **New Data Models:** MusicAsset, PodcastAsset, ContentRequest, ContentType, MusicGenre, VideoQuality, PodcastFormat
- **New API Endpoints:** `/v1/queue`, `/v1/finance`, `/v1/providers/health`, `/v1/music`, `/v1/podcasts`, `/v1/approvals`, `/v1/request`, `/v1/generate/*`, `/v1/approve/*`, `/v1/publish/*`
- **New CLI Command:** `blue-waves cockpit` starts server with Cockpit dashboard on port 8420
- **New Configuration:** 30+ environment variables for providers, scheduling, quality gates, publishing
- **New Tests:** 17 governance harness tests, 14 engine tests (50 total)
- **New Documentation:** BLUE_WAVES_V020.md, CHANGELOG.md, CONSTITUTION.md, README.md

### Changed
- **models.py:** Added AssetStatus values (QUEUED, COMPOSING, MIXING, VOICE_RECORDING, QUALITY_CHECK, READY_TO_PUBLISH, AUTO_APPROVED), ContentType, MusicGenre, VideoQuality, PodcastFormat enums
- **governance.py:** Extended Policy with max_weekly_music/podcasts/videos, max_podcast_duration_minutes, max_music_duration_seconds, auto_approve_under_cents, quality_gate_threshold, provider_fallback_enabled. Added assert_autonomous_generation_allowed, assert_quality_gate, assert_provider_fallback, assert_publishable_music, assert_publishable_podcast, assert_generation_allowed methods
- **config.py:** Added 30+ configuration fields for music/TTS/video providers, publishing, cockpit, scheduler, quality gates
- **providers.py:** Added MusicProvider, TTSProvider, VideoProvider protocols. Added ACEStepMusicProvider, SunoMusicProvider, KokoroTTSProvider, EdgeTTSProvider, GoogleTTSProvider, KlingVideoProvider, SeedanceVideoProvider, KenBurnsProvider, ProviderRegistry, ProviderHealthMonitor
- **hybrid.py:** Added new Stage values (MUSIC_COMPOSITION, MUSIC_MIXING, PODCAST_SCRIPT, PODCAST_VOICE, PODCAST_MIX, VIDEO_GENERATION, VIDEO_RENDER). Added route_music, route_podcast, route_video methods for quality-aware routing
- **application.py:** Integrated MusicEngine, PodcastEngine, VideoEngine, FinanceEngine, ContentQueue, Scheduler, QualityGates, ProviderRegistry, ProviderHealthMonitor. Added generate_music, generate_podcast, generate_video, approve_music, approve_podcast, publish_music, publish_podcast, add_content_request, get_queue_status, get_finance_status, get_health_status methods
- **service.py:** Added 14 new API endpoints for queue, finance, providers, music, podcasts, approvals, generation, and publishing. Added Cockpit dashboard HTML at `/`
- **cli.py:** Added `cockpit` command with --host and --port options
- **pyproject.toml:** Updated version to 0.2.0, added ruff and mypy configuration

### Fixed
- PodcastAsset `now_iso()` call error (was calling function instead of passing reference)
- VideoEngine transition error (was transitioning from IDEA to PRODUCED, now creates with PRODUCED status)
- Scheduler missing `field` import

## [0.1.0] - 2026-08-31

### Added
- Initial release with bilingual lesson workflow
- 8 crew agents: MIRA, ZACK, BELAL, MAYAR, LEO, JOE, NELLY, KOYOSHU
- Hybrid compute router (local-first, cloud escalation)
- Append-only ledger with SHA-256 hash chain
- Governance with fail-closed policy enforcement
- HTTP API with health, agents, register, lessons, assets, approve, publish, metrics, review endpoints
- CLI with health, agents, register, demo, review, serve commands
- 36 tests covering governance, hybrid, ledger, and pipeline