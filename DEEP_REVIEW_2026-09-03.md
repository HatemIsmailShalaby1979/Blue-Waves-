# Blue Waves — Deep Architecture, Code & Profitability Review

**Date:** 2026-09-03  
**Scope:** Repository structure, architecture, code quality, security, governance alignment, and profit-track gaps  
**Reviewer:** SWE (deep automated review)

---

## Executive Verdict

The Blue Waves codebase is **architecturally sound for a single-operator content studio** — the governance model, append-only ledger, fail-closed approval gates, and hybrid provider routing are well-conceived and genuinely functional. However, the project sits at **$0 revenue with two fatal blockers** that no amount of code quality will fix: **(1) the output quality is far below what the YouTube/podcast market rewards**, and **(2) there is no audience acquisition engine**. The code can publish; it cannot attract.

**Profit probability without changes:** 15-25%  
**Profit probability with recommended fixes:** 55-70%  
**Time to first dollar:** 6-10 weeks (requires owner action, not just code)

---

## 1. Repository Structure Review

### What's Right
- Clean `src/blue_waves/` package layout with 26 modules, clear separation of concerns
- Append-only JSONL stores (`assets.jsonl`, `audit.jsonl`, `music.jsonl`, `podcasts.jsonl`) — no database dependency, appropriate for single-tenant
- Governance docs (`CONSTITUTION.md`, `DECISIONS.md`, `PROFIT_AUDIT.md`) are versioned and aligned with code
- `.gitignore` correctly excludes `.env`, `data/`, `__pycache__/`
- `pyproject.toml` uses modern setuptools with optional dependency groups

### What's Wrong

| Issue | Severity | Detail |
|-------|----------|--------|
| **`.pyc` files committed** | Medium | 26 `.pyc` files in `src/blue_waves/` — should be gitignored and never committed; they leak build artifacts and cause stale-code bugs across environments |
| **Duplicate `cockpit/` module** | Medium | `cockpit/app.py` duplicates `service.py` approval logic — two code paths for the same operation, drift risk |
| **Version mismatch** | Low | `pyproject.toml` says `0.2.0`, README says `v0.2.1`, CHANGELOG has `0.2.2` entries — three different versions in the same repo |
| **`docs/` has only 2 files** | Low | `BLUE_WAVES_V020.md` and `BLUE_WAVES_EXPANSION_PLAN.md` — no API reference, no contributor guide, no architecture decision records beyond `DECISIONS.md` |
| **No CI/CD pipeline** | High | No `.github/workflows/`, no GitLab CI, no pre-commit hooks — tests run only if someone remembers to run them |
| **`start_cockpit.py` at root** | Low | Duplicates `blue-waves cockpit` CLI entry point — two ways to start the same thing |

---

## 2. Architecture Review

### 2.1 Governance Model — STRONG

The two-gate approval model (Gate 1: topic approval, Gate 2: content approval) is correctly implemented:

- `governance.py` enforces fail-closed: `assert_publishable()` checks tenant, channel allowlist, approval status, approval_id presence, and weekly cap
- `assert_owner()` blocks non-owner actors from approving
- Self-approval is explicitly denied (`requested_by == approver` → `GovernanceViolation`)
- Preview-before-approval guard (`_assert_preview_exists`) checks actual file existence and non-zero size
- Quality gate threshold (0.7) auto-rejects below-threshold assets

**Gap:** The quality gate (`quality_gates.py`) is weak — it only checks file existence, file size > 0, and asset status. It does **not** assess actual content quality (audio levels, silence ratio, video resolution, speech coverage). The `toolchain.py` has `measure_silence_ratio()` and `probe_media()` functions that are **never called by the quality gate**. This is the single biggest quality gap.

### 2.2 Hybrid Compute Router — SOUND BUT UNTESTED

`hybrid.py` routes local-first with cloud escalation:
- Motion stage: checks cloud budget > 0, then uses configured cloud provider; falls back to Ken Burns
- Music: free→ace_step, standard→ace_step, high→suno_api
- Video: draft→ken_burns, standard→seedance, high→kling

**Gap:** The cloud video providers (`KlingVideoProvider`, `SeedanceVideoProvider`) are **stubs** — they raise `ProviderUnavailable("requires API key verification")` even when keys are configured. No actual API integration exists. The `AimlapiMusicProvider` and `KaiMusicProvider` have real HTTP calls but their response parsing assumes a specific API contract that may not match reality.

### 2.3 Append-Only Ledger — CORRECT

`ledger.py` implements a SHA-256 hash chain:
- Each record carries `previous_hash` and computes `record_hash` over a canonical JSON
- `verify()` walks the chain and detects tampering
- The hash excludes `record_hash` before computing (correct — prevents circular dependency)

**Gap:** The ledger is stored as a plain text file with no rotation. At 82KB after 2 days of testing, it will grow unbounded in production. No archival strategy exists.

### 2.4 Provider Registry — WELL-STRUCTURED BUT INCOMPLETE

`providers.py` is the largest module (~980 lines) and handles all provider types:
- Text providers: 6 configured (local LM Studio + 5 cloud)
- Music providers: aimlapi, kai, ace_step, local_audio_fallback
- TTS providers: kokoro, edge_tts, local_tts_fallback, google_tts
- Video providers: kling, seedance, ken_burns

**Gaps:**
- `ALLOWED_OPENAI_HOSTS` and `ALLOWED_MEDIA_HOSTS` are **defined twice** (lines 226-262) — duplicate code blocks
- `KokoroTTSProvider.generate()` always raises `ProviderUnavailable` — it's a stub
- `GoogleTTSProvider.generate()` always raises — it's a stub
- `ACEStepMusicProvider.generate()` always raises — it's a stub
- The `OfflineMusicProvider` uses `music_synth.py` which generates raw PCM with a simple LCG random number generator — this produces **deterministic but musically primitive** output
- The `KenBurnsProvider._generate_bg_music()` also uses raw PCM synthesis — the background music is a basic chord progression with a kick drum, not competitive quality

---

## 3. Code Quality Review

### 3.1 Clean Code Issues

| File | Issue | Severity |
|------|-------|----------|
| `providers.py` | Duplicate `ALLOWED_OPENAI_HOSTS` / `ALLOWED_MEDIA_HOSTS` blocks (lines 226-262) | Medium |
| `service.py` | 636-line monolithic HTML string embedded in Python — no template separation | Medium |
| `service.py` | Inline JavaScript with no CSRF tokens, no input sanitization on `innerHTML` | High |
| `application.py` | `save_connection()` reaches into engine internals (`self.music_engine._providers = ...`) — breaks encapsulation | Medium |
| `application.py` | `connections._read()` called directly (private method) in `__init__` | Low |
| `podcast_engine.py` | `_select_tts_provider` uses `and/or` chaining for boolean logic — fragile, not explicit | Low |
| `governance.py` | `assert_publishable_music()` and `assert_publishable_podcast()` type-hint `asset: object` instead of `MusicAsset`/`PodcastAsset` | Low |
| `youtube_upload.py` | `create_youtube_service_from_oauth()` writes token JSON to disk without `chmod 0o600` | Medium |
| `finance.py` | `get_weekly_costs()` returns ALL costs, not just this week's — misleading name | Medium |
| `scheduler.py` | `execute_due_jobs()` marks jobs as "running" but never actually executes them — no callback to application | High |
| `service.py` | `_serve_media()` reads entire file into memory (`body = resolved.read_bytes()`) — no streaming, no range support despite `Accept-Ranges` header | Medium |

### 3.2 Dead Code

- `cockpit/` directory (app.py, routes/, templates/) appears to be an abandoned FastAPI-based cockpit attempt — the actual cockpit is the embedded HTML in `service.py`
- `DeferredMotionProvider` is a placeholder that always raises
- `_generate_silence()` in `KenBurnsProvider` — appears unused (the TTS failure path now raises instead of substituting silence)
- `queue.py` `ContentRequest` has `video_path`, `music_path`, `audio_path` fields but the queue is never wired to actual generation

### 3.3 Error Handling

- `service.py` `do_POST()` catches all exceptions and returns `{"error": str(exc)}` — this **leaks internal error messages** to API callers, including file paths and stack trace fragments
- `application.py` `_init_youtube_service()` catches `Exception` and logs but continues — correct for startup resilience, but the log message goes only to the ledger, not to any monitoring surface
- `providers.py` catches `Exception` broadly in `EdgeTTSProvider.generate()` — appropriate for a fallback provider

---

## 4. Security Review

### 4.1 CRITICAL — Live Secrets in Plaintext

**`data/connections.json` contains live API keys and OAuth tokens:**
- YouTube OAuth client ID, client secret, access token, and refresh token
- OpenRouter API key (`sk-or-v1-...`)
- Groq API key (`gsk_...`)
- NVIDIA NIM API key (`nvapi-...`)
- aimlapi API key (`2da85e9e...`)
- KAI API key (`4d59632f...`)

**`data/youtube_token.json`** contains the YouTube OAuth token JSON.

These files are in `data/` which is `.gitignore`d (good), but:
1. They are stored in **plaintext** with only `chmod 0o600` on connections.json (which may not work on Windows)
2. The YouTube token file (`youtube_token.json`) is written by `create_youtube_service_from_oauth()` **without any chmod call**
3. If the data directory is ever synced to cloud storage, backed up to an unencrypted target, or accessed by another process, all keys are exposed

**Recommendation:** Encrypt secrets at rest using a key derived from the owner's password, or use the OS keychain (Windows Credential Manager / macOS Keychain / Linux secret-service).

### 4.2 HIGH — No Authentication on Cockpit HTTP Server

The `BlueWavesHandler` in `service.py` has **zero authentication**:
- `cockpit_host` defaults to `0.0.0.0` (all interfaces)
- `cockpit_password_hash` defaults to `""` (empty — no password set)
- `cockpit_secret_key` defaults to `"change-me-in-production"` and is never used
- Any network-accessible client can: generate content, approve content, publish to YouTube, save API keys, and start OAuth flows

**This is the most dangerous issue in the codebase.** If the cockpit is running on `0.0.0.0:8420`, anyone on the same network can publish content to the linked YouTube channel or steal API keys via `POST /v1/connections`.

**Recommendation:** 
1. Default `cockpit_host` to `127.0.0.1`
2. Implement HTTP Basic Auth using `cockpit_username` + `cockpit_password_hash`
3. Require a valid `cockpit_secret_key` header for all mutating endpoints
4. Block `0.0.0.0` binding unless an explicit override is set

### 4.3 MEDIUM — SSRF Protection Incomplete

`_validate_url()` in `providers.py` checks hostname against an allowlist, which is good. However:
- It does not check for DNS rebinding (a hostname that resolves to `127.0.0.1` or `169.254.169.254`)
- It does not resolve the hostname and check the IP against private ranges
- The allowlists are hardcoded and don't include `router.huggingface.co` (which is in the config as `huggingface_base_url`)

### 4.4 LOW — XSS in Cockpit Dashboard

The Cockpit HTML uses `innerHTML` extensively with unsanitized data:
```javascript
document.getElementById('library').innerHTML = library.map(a => {
  return `<div class="card"><h2>${a.title || a.topic}</h2>...`;
```
If a content title or topic contains HTML (e.g., `<script>`), it will be executed in the browser. Since titles come from owner input, this is low-risk but still bad practice.

### 4.5 GOOD — No Shell Injection

All `subprocess.run()` calls use **parameter lists** (no `shell=True`). Input validation exists on `voice_id` in EdgeTTSProvider. This is correctly done.

---

## 5. Governance Alignment Review

### Constitution vs. Implementation

| Article | Implementation | Status |
|---------|----------------|--------|
| Art. 1: Human Sovereignty | `assert_owner()`, `approve()` requires owner actor | ✅ Aligned |
| Art. 2: Fail-Closed | All publish/approve methods check status, approval_id, cap | ✅ Aligned |
| Art. 3: Two-Gate | Gate 1 (topic) via `create_bilingual_lesson`, Gate 2 via `approve_*` | ⚠️ Gate 1 not enforced for music/podcast/video (only lessons) |
| Art. 4: Agent Authority | `agents.py` defines roles; governance checks actor in approve | ✅ Aligned |
| Art. 5: Hybrid Compute | `hybrid.py` routes local-first; budget checked | ✅ Aligned |
| Art. 6: Append-Only Ledger | SHA-256 chain, verified on read | ✅ Aligned |
| Art. 7: Content Quality | Quality gate exists but only checks file existence | ⚠️ Below standard |
| Art. 8: Financial Responsibility | Budget ceiling enforced; cost tracking exists | ⚠️ All costs logged as 0 cents — no real cost tracking |
| Art. 9: Transparency | Cockpit shows health, queue, finance, approvals | ✅ Aligned |
| Art. 10: Amendment | Constitution says owner-only; `DECISIONS.md` tracks | ✅ Aligned |

### Critical Governance Gap

**Article 7 (Content Quality) is not met.** The Constitution says "Quality Gates: Auto-approve if score >= threshold (0.7), auto-reject below." But the quality gate (`check_media_asset`) only checks:
1. Does the file exist?
2. Is the file non-empty?
3. Is the asset status `AWAITING_OWNER`?

This means **any non-empty file passes the quality gate**. A 1-byte WAV file would pass. The `toolchain.py` module has the tools to do real quality assessment (`probe_media()`, `measure_silence_ratio()`, `probe_duration()`) but they are **never integrated into the quality gate**. This is the root cause of the "output quality is way below reasonable" problem.

---

## 6. Profit Gap Analysis

### 6.1 Revenue Blockers (Fatal)

| Blocker | Root Cause | Fix Effort | Owner Action Required |
|--------|------------|------------|----------------------|
| **Output quality uncompetitive** | Music is raw PCM synth; video is gradient+text+TTS; quality gate doesn't assess quality | 40-60h code | Cloud provider API keys with verified terms |
| **No audience** | No SEO beyond title/tags; no thumbnail strategy; no cross-platform distribution; no community engagement | 20-30h code | Content niche selection, consistent publishing |
| **No monetization path** | Videos upload as "private"; no AdSense connection; no sponsor outreach; no merchandise | 10h code | AdSense application, sponsor outreach |

### 6.2 Output Quality Deep-Dive

**Music:** The `OfflineMusicProvider` (used when no cloud provider is configured) generates music via `music_synth.py`, which creates raw 16-bit PCM with a Linear Congruential Generator (LCG) for randomness. The output is:
- Single channel (mono)
- Simple chord progressions with basic envelopes
- A kick drum and hi-hat made from filtered noise
- No reverb, no mastering, no stereo width

This is **functionally a ringtone from 2005**, not competitive with Suno, Udio, or even royalty-free library music. YouTube's Content ID may flag it as low-quality or derivative.

**Video:** The `KenBurnsProvider` generates:
- A solid color gradient background (two colors blended over time)
- Text overlay with the prompt/title
- TTS narration (Edge-TTS, which is decent)
- Background music from the same PCM synth

The video is a **static image with text and narration** — this is a slideshow, not a video. YouTube's algorithm and viewers reward visual dynamism, thumbnails, and editing patterns that this cannot produce.

**Podcast:** The `PodcastEngine` is the strongest output:
- Edge-TTS for voice (decent quality, multiple voices)
- Dialogue support (host/guest with different voices)
- Intro/outro music (from PCM synth)
- Audio concatenation via FFmpeg with proper sample rate conversion

The podcast output is **listenable but not competitive** — the voices are robotic, the music is primitive, and there's no editing or pacing variation.

### 6.3 Cost Tracking is Fake

`_record_generation_cost()` always logs `credits=0, estimated_cents=0`:
```python
def _record_generation_cost(self, content_type: str, asset_id: str, provider: str) -> None:
    event = CostEvent(..., amount_cents=0, description="local/offline generation")
    self.finance.log_cost(provider, content_type, asset_id, credits=0, estimated_cents=0)
```

This means:
- The finance dashboard always shows $0.00
- SHIPO cannot recommend cost-saving provider switches (it has no data)
- The budget ceiling enforcement is meaningless (spent is always 0)

### 6.4 Scheduler is a No-Op

`Scheduler.execute_due_jobs()` marks jobs as "running" but never calls any generation or publish method. It's a data structure with no execution engine. The scheduler also doesn't persist jobs (`self._jobs` is in-memory only) — restart loses all scheduled jobs.

---

## 7. Prioritized Fix Roadmap

### Sprint 1: Security & Foundation (Week 1)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | **Rotate all exposed API keys** (aimlapi, KAI, YouTube OAuth, OpenRouter, Groq, NVIDIA) — they are in plaintext on disk | 2h | Critical security |
| P0 | **Add HTTP Basic Auth to cockpit** — default to `127.0.0.1` binding | 4h | Critical security |
| P0 | **Encrypt `connections.json` at rest** — use OS keychain or password-derived AES | 8h | Critical security |
| P1 | **Fix duplicate `ALLOWED_*_HOSTS`** in providers.py | 0.5h | Code quality |
| P1 | **Remove committed `.pyc` files** and add to `.gitignore` | 0.5h | Repo hygiene |
| P1 | **Fix version mismatch** — align pyproject.toml, README, CHANGELOG | 0.5h | Repo hygiene |
| P1 | **Stream media responses** instead of reading entire file into memory | 4h | Performance |
| P2 | **Add pre-commit hooks** (ruff, mypy) and a CI workflow | 4h | Process |

### Sprint 2: Quality Gate (Week 2)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | **Integrate `probe_media()` and `measure_silence_ratio()` into quality gates** — reject assets with >40% silence, check duration, sample rate, channels | 8h | Quality |
| P0 | **Add speech coverage check** — TTS audio must cover >=80% of target duration | 4h | Quality |
| P0 | **Add loudness compliance check** — reject assets outside -16 to -14 LUFS | 4h | Quality |
| P1 | **Wire scheduler to actual generation** — `execute_due_jobs()` must call `generate_*` and `publish_*` | 8h | Automation |
| P1 | **Persist scheduler jobs** to JSONL | 4h | Reliability |
| P1 | **Implement real cost tracking** — use provider API response `usage` data | 8h | Finance |

### Sprint 3: Output Quality (Weeks 3-4)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | **Connect a verified cloud music provider** (Suno API or aimlapi with verified terms) — replace PCM synth for "high" quality | 16h | Revenue-enabling |
| P0 | **Connect a verified cloud video provider** (Kling or Seedance with verified terms) — replace Ken Burns for "high" quality | 24h | Revenue-enabling |
| P1 | **Add thumbnail generation** — use PIL/Pillow to create 1280x720 thumbnails from video first frame + title text | 8h | CTR |
| P1 | **Add video intro/outro** — brand ident at start and end of every video | 8h | Brand |
| P2 | **Add subtitle/caption track** — SRT generation from script, upload to YouTube | 8h | Accessibility/SEO |
| P2 | **Add cross-platform publishing** — TikTok, Instagram Reels (shorts from long-form) | 16h | Distribution |

### Sprint 4: Audience & Monetization (Weeks 5-8)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | **Set YouTube videos to "public" after owner approval** (currently always "private") | 2h | Revenue |
| P0 | **Apply for YouTube Partner Program** (1,000 subs + 4,000 watch hours) | Owner | Revenue |
| P1 | **Submit podcast RSS to Apple Podcasts, Spotify, Google Podcasts** | 4h + Owner | Distribution |
| P1 | **Implement analytics auto-sync** — fetch YouTube stats daily, feed to KOYOSHU | 8h | Learning loop |
| P1 | **Build content calendar** — 3 publishes/week on consistent schedule | 8h | Consistency |
| P2 | **Sponsorship media kit** — channel stats, audience demo, rate card | Owner | Revenue |

---

## 8. Test Coverage Assessment

**Claim:** 52 tests passing  
**Verified:** 44 of 52 pass (8 tests in `test_pipeline.py` and `test_cockpit_e2e.py` could not run due to a broken `cryptography` package in the test environment — not a code bug, but a dependency management gap)

**Missing test coverage:**
- No tests for the HTTP API security boundary (no auth tests)
- No tests for SSRF protection bypass attempts
- No tests for quality gate with real media files
- No tests for YouTube upload (mocked but not integration-tested)
- No tests for scheduler execution (because it doesn't execute)
- No tests for cost tracking accuracy
- No tests for ledger tamper detection (the `verify()` method)
- No tests for concurrent access to the in-memory asset stores

**`pyproject.toml` test dependencies are incomplete:** `test = ["pytest>=8"]` but the tests import `respx` (requires `httpx`) and `edge-tts` — these are undeclared dependencies.

---

## 9. Summary of Findings by Severity

### Critical (Must Fix Before Any Production Use)
1. **Live API keys in plaintext** on disk in `data/connections.json` and `.env`
2. **No authentication on cockpit HTTP server** — anyone on the network can publish to YouTube or steal keys
3. **Quality gate is cosmetic** — only checks file existence, not content quality
4. **All cloud video/music providers are stubs** — no real cloud generation possible

### High (Blocks Profit)
5. **Scheduler doesn't execute jobs** — no automated publishing
6. **Cost tracking always logs 0** — SHIPO and budget enforcement are non-functional
7. **No CI/CD pipeline** — no automated quality gates on code changes
8. **Output quality uncompetitive** — PCM synth music and gradient videos won't attract viewers

### Medium (Technical Debt)
9. Duplicate code blocks in `providers.py`
10. Monolithic HTML in `service.py` (636 lines)
11. `save_connection()` breaks encapsulation by reaching into engine internals
12. Error messages leaked to API callers
13. Media served via full-file read (no streaming/range support)
14. Version mismatch across docs
15. `youtube_token.json` written without file permissions

### Low (Polish)
16. `.pyc` files in repo
17. Duplicate cockpit module (`cockpit/` vs embedded HTML)
18. Dead code (`_generate_silence`, `DeferredMotionProvider`)
19. Type hints use `object` instead of specific asset types
20. `get_weekly_costs()` returns all-time costs, not weekly

---

## 10. Path to Profit — Concrete Sprint Plan

### Phase 0.5: Security Hardening (This Week)
1. Rotate ALL exposed credentials immediately
2. Add HTTP Basic Auth to cockpit
3. Default cockpit to `127.0.0.1`
4. Encrypt secrets at rest
5. Remove `.pyc` from repo

### Phase 1: Quality Gate + Real Providers (Weeks 2-3)
1. Integrate `probe_media()` + `measure_silence_ratio()` into quality gates
2. Connect ONE verified cloud music provider (start with the one whose terms allow commercial use)
3. Connect ONE verified cloud video provider
4. Implement real cost tracking from API responses
5. Wire scheduler to actual generation + publish

### Phase 2: Audience Engine (Weeks 4-6)
1. Set published videos to "public" (with owner override)
2. Generate and upload custom thumbnails
3. Submit podcast RSS to directories
4. Implement daily analytics sync
5. Build content calendar with 3 publishes/week

### Phase 3: Monetization (Weeks 7-10)
1. Apply for YouTube Partner Program
2. Track RPM and CTR per content type
3. Build media kit for sponsors
4. Activate KOYOSHU learning loop with real metrics
5. A/B test titles and thumbnails

### Kill Criteria (Preserved from Profit Audit)
- <500 views/mo after 20 publishes → abandon content path
- Cloud cost > $200 with <$100 revenue → hard stop cloud
- No revenue after Month 3 → evaluate SaaS pivot or sunset

---

**Bottom line:** The codebase is a well-governed, correctly-architected studio control plane that cannot currently produce competitive content or attract an audience. The governance and ledger are production-grade; the output quality and audience engine are pre-production. Fix the security issues this week, integrate real quality gates and cloud providers in weeks 2-3, and start a measured publishing cohort in week 4. First dollar is achievable in 6-10 weeks if the owner commits to consistent publishing and provider integration.

---

## Resolution — Quality Sprint v0.3.0 (2026-09-04)

Continued from Phase 8 (cockpit full control board). This agent completed Phases 9–11:

- **Scheduler automation (Phase 9):** `Scheduler.tick()` now picks up queued requests,
  routes via the executor, retries with enhancement notes (max 3 attempts), and updates
  queue stages. `BlueWavesApplication.run_automated_cycle()` implements the full
  pipeline (queue → generate → quality gate → awaiting_owner, retry ×3, ledger-logged
  every step, cycle summary). `run_scheduler_tick()` wraps automated cycle + tick +
  due jobs + analytics. Bounded scheduler durations (music 60s / podcast 60s / video 5s).
- **Cockpit gaps closed (Phase 8 remainder):** `GET /api/quality/{asset_id}`,
  `GET /api/video-use/status`, `POST /api/video-use/edit/{asset_id}` with
  `get_quality_breakdown` / `get_video_use_status` / `trigger_video_use_edit`.
- **Blocker fixes:** `ContentAsset.metadata` added (video generation crashed);
  `EdgeTTSProvider` maps ElevenLabs voice IDs to Edge voices; bare `PodcastEngine`
  falls back to local TTS; `MusicEngine` always attaches structured lyrics;
  `test_health_monitor_get_fallback` updated to the Phase 2 chain
  (suno_api → aimlapi_music, kokoro → elevenlabs_tts → edge_tts).
- **E2E tests (Phase 10, 19 new):** `test_e2e_video_quality` (1080p h264 + video-use),
  `test_e2e_music_quality` (48kHz stereo + lyrics structure),
  `test_e2e_podcast_quality` (two voices + dialogue),
  `test_quality_gate_real` (missing preview / duration mismatch / silent podcast / bogus file),
  `test_shepo_finance` (real costs, revenue projection, break-even),
  `test_cockpit_full_board` (generate ×3, SHEPO crew, finance costs, quality breakdown),
  `test_scheduler_automation` (tick success, retry-exhaustion, automated cycle).
- **Docs & release (Phase 11):** README v0.3.0, CONSTITUTION Article VIII (SHEPO agent
  of record), CHANGELOG 0.3.0, `.env.example` (`VIDEO_USE_SKILL_PATH`), version bumps
  (`__init__`, application health, cockpit UI/server).
- **Verification:** new suites pass (19/19); `test_engines` (14/14) fixed;
  `test_cockpit_e2e` (2/2) passes after the metadata fix. Full-suite spot checks green.
- **Remaining (out of sprint scope):** cloud providers still need owner API keys +
  terms approval (fail-closed by design); audience acquisition engine and revenue
  remain pre-production per the profit audit; `.pyc` cleanup / CI pipeline untouched.
