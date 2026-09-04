# Changelog

## 0.3.0 — 2026-09-04 (Quality Sprint)

Maximize generated-media quality to compete with real YouTube creators: video-use
post-production, Suno music, ElevenLabs podcasts, real quality gates, SHEPO finance
agent, cockpit full control board, scheduler automation, E2E quality tests.

### Quality Sprint — Phases 9–11 (scheduler automation, E2E, release)
- **Scheduler automation** — `Scheduler.tick()` picks up queued requests, routes via
  the executor, retries with enhancement notes (max 3 attempts), updates queue stages.
  `BlueWavesApplication.run_automated_cycle()` runs generate → quality gate →
  awaiting_owner with per-attempt ledger logging and a cycle summary.
  `run_scheduler_tick()` now wraps automated cycle + tick + due jobs + analytics.
  Scheduler podcast/music/video use bounded durations (60s/60s/5s) so automation stays fast.
- **Cockpit gaps closed** — `GET /api/quality/{asset_id}` (review-panel breakdown),
  `GET /api/video-use/status`, `POST /api/video-use/edit/{asset_id}` (manual post-production).
- **Blocker fixes** — `ContentAsset` gains `metadata` (video generation crashed on
  `asset.metadata`); `EdgeTTSProvider` maps ElevenLabs voice IDs to Edge voices so the
  ElevenLabs-first chain degrades gracefully; bare `PodcastEngine` falls back to
  local TTS; `MusicEngine` always attaches structured lyrics.
- **E2E tests (19 new)** — `test_e2e_video_quality`, `test_e2e_music_quality`,
  `test_e2e_podcast_quality`, `test_quality_gate_real`, `test_shepo_finance`,
  `test_cockpit_full_board`, `test_scheduler_automation`.
- **Docs** — README v0.3.0 (SHEPO, Suno/ElevenLabs, video-use, quality table),
  CONSTITUTION Article VIII (SHEPO agent of record), DEEP_REVIEW Resolution.

### Phases 1–8 (prior agent — retained)
Comprehensive single-panel owner control board plus the three-layer zero-cost quality transformation.

### Zero-cost quality transformation
- Added persisted quota-aware provider rotation with daily/monthly reset, reservation/release, budget checks, capability metadata, and Cockpit visibility.
- Added FFmpeg-first audio mastering and video mastering with source/output SHA-256 provenance.
- Added stronger video quality proxies for frame rate and bitrate; removed provider-based auto-approval shortcuts for music and podcasts.
- Added asynchronous free-GPU job orchestration contract with explicit unknown-outcome and artifact validation states.
- Fixed Cerebras and Hugging Face OpenAI-compatible host allowlisting and declared NumPy for local music synthesis.


### Added
- **Encrypted secrets at rest (AES-256-GCM + master password)** — `crypto.py` (`SecretCipher`, PBKDF2-HMAC-SHA256, 600k iterations, per-record salt). `connections.py` now encrypts `api_key`/`access_token`/`refresh_token`/`client_secret`/`oauth_state` and decrypts only in memory. Plaintext fallback when `BLUE_WAVES_MASTER_PASSWORD` is unset. `cryptography>=42` added; documented in `.env.example`.
- **Provider approval gating** — `provider_approvals.py` with a `REQUIRE_APPROVAL` set (openrouter, groq, nvidia_nim, cerebras, huggingface, suno, kling, seedance, kokoro, aimlapi, kai). `ProviderRegistry` guards `get_{text,music,tts,video}_provider` and fails closed until the owner approves cloud terms via the cockpit.
- **Podcast RSS feed** — `GET /feed/rss.xml` on the cockpit, honoring `COCKPIT_PUBLIC_BASE_URL` (or the cockpit host/port). `.env.example` documents `COCKPIT_PUBLIC_BASE_URL`.
- **Analytics / scheduler controls** — `sync_all_published_metrics()`, `run_scheduler_tick()`; cockpit panels `/api/analytics/sync`, `/api/scheduler/tick`, `/api/metrics`.
- **Monetization** — `monetization.py` with `SponsorTracker` (outreach…declined pipeline), `MediaKitGenerator` (channel/media-kit summary), and outreach email template; cockpit `/api/sponsors`, `/api/monetization/mediakit`, `/api/sponsors/{id}/email`.
- **Expanded Cockpit SPA** (`cockpit_ui.py`) — single-page board with: overview/health, media library with inline `<audio>`/`<video>` previewers, approve/reject/retry-with-feedback/publish controls, pending-approval queue, crew member monitoring with a task board, generation forms (music/podcast/video/queue), finance plan with budget/goal and responsible owners, metacognition (SHIPO + KOYOSHU performance ranking with owner approval), provider terms approval and API-key entry that hides and encrypts after save, scheduler stats and tick, sponsor/media-kit panel.
- **Scheduler executor wiring** — `scheduler.py` gained an `executor` callable; `execute_due_jobs` transitions running→completed/failed and stores the result.
- **`cockpit_server.py` endpoints** — `get_crew`, `_derive_tasks`, `get_library`, `_media_exists`, `get_media_path`, `reject_media`, `retry_media`, `publish_media`, `get_intelligence`, `approve_recommendation`, `get_scheduler`, `get_finance_plan`, `get_connections`, `save_connection`, `generate_media`; routes `/api/crew`, `/api/library`, `/api/intelligence`, `/api/finance/plan`, `/api/scheduler`, `/api/connections`, `/api/generate/{music,podcast,video}`, `/media/{type}/{id}`, plus POST `/api/{approve,reject,retry,publish}/{type}/{id}`, `/api/memory/approve`, `/api/scheduler/tick`, `/api/analytics/sync`.
- **`compat.py`** — `StrEnum` backport so the package runs on Python 3.10 (used by `models.py`, `hybrid.py`).

### Changed
- `config.py` — default `cockpit_host` is now `127.0.0.1` (was `0.0.0.0`); added `cockpit_public_base_url`.
- `cli.py` — `blue-waves cockpit` correctly calls `start_cockpit` (was erroneously calling `service.serve`) and binds to the configured host/port.
- `.env.example` — added `BLUE_WAVES_MASTER_PASSWORD`, `COCKPIT_HOST=127.0.0.1`, `COCKPIT_PUBLIC_BASE_URL`.
- Cockpit dashboard UI moved out of `cockpit_server.py` into a dedicated `cockpit_ui.py` module.

### Fixed (found during cockpit media-quality testing, 2026-09-03)
- **Cockpit route index bug** — `/api/approve|reject|retry|publish/{type}/{id}` and `/api/generate/{type}` parsed the wrong path segment (`parts[2]` instead of `parts[3]`), so every action hit "unknown content type". All action routes now use the correct indices.
- **Approval dropped the HTTP connection on gate blocks** — `approve_content` let `GovernanceViolation` propagate and kill the connection; it now returns a structured `{"error": ...}` like the reject/retry/publish paths.
- **Ken Burns render failed on Windows** — the `drawtext=textfile={windows_path}` filter broke on the `C:` colon (two-level FFmpeg filter escaping was missing) and drawtext without `fontfile` crashed where fontconfig has no config. Paths are now escaped for both parsing levels and the font comes from the existing cross-platform `find_font(bold=True)` helper (`providers.py`).
- **Quality gate crashed on real media** — `quality_gates.py` referenced `Toolchain` without importing it, constructed it with a non-existent `Settings.ffprobe_bin`, and called `probe_media`/`measure_silence_ratio` as methods instead of the module-level functions. Now uses `Toolchain.from_settings()` plus the module functions.
- **Quality-gate finding (by design, open product question)** — the gate correctly blocks local-tier media: the local music fallback renders 44.1 kHz mono and Edge-TTS narration inherits 24 kHz mono, while the delivery spec requires stereo 48 kHz. Approvals stay blocked until renders are normalized or the spec is relaxed.

### Changed (media-quality testing follow-up, 2026-09-03)
- **Local renderers normalized to the delivery spec (stereo 48 kHz)** — `music_synth.py` now synthesizes at 48 kHz (`SR = 48000`, stereo throughout); `podcast_engine._concat_audio` renders the final mix at `AUDIO_SAMPLE_RATE`/`AUDIO_CHANNELS` instead of hardcoded 44.1 kHz; Ken Burns `_generate_bg_music`, `_generate_silence`, and the `_tone_wav` TTS fallback are 48 kHz stereo as well.
- **Verified end-to-end (2026-09-03)** — fresh music, podcast (duration-matched script), and Ken Burns video each approved with `quality_score: 1.0` via the cockpit API. The gate still correctly blocks under-filled content (silence ratio ≥ 0.4, e.g. a 60 s target with ~32 s of speech) and non-`awaiting_owner` assets, returning structured JSON errors.
- QA assets from this testing phase removed (7 records + 13 media files); ledger/audit history preserved.

### Fixed (API-key configuration audit, 2026-09-03)
- **Runtime key saves dropped the approval gate** — `save_connection` rebuilt `ProviderRegistry` without `approval_store`, silently disabling fail-closed approval after any UI key save. Now passes `approval_store=self.provider_approvals`.
- **UI-saved video/TTS/music keys lost on restart** — startup only reloaded 6 text/music providers from the encrypted store, so kling/seedance/kokoro/aimlapi/kai keys entered via the cockpit vanished on the next restart. All 11 UI-managed providers now reload, and `save_connection` maps aimlapi/kai keys too.

## 0.2.2 — 2026-09-03

- Added real cockpit E2E coverage for generation, preview streaming, rejection, enhanced retries, and owner approval.
- Added retry lineage and quality evidence to every media asset.
- Added configured free/developer-tier cloud text-provider catalog and fallback orchestration.
- Fixed YouTube audio publishing by packaging WAV assets as MP4 videos and fixed SEO title formatting.

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
- aimlapi API credentials are supported for cloud music generation.
- Unconfigured cloud providers fail closed and use local fallbacks where available.

## [0.2.0] - 2026-09-01

### Added
- **Music Engine (BELAL):** ACE-Step (local ROCm) and aimlapi (cloud) music generation
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
