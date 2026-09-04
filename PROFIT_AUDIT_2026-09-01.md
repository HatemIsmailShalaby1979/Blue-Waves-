# Blue Waves — Profit Audit & Remediation Plan
**Date:** 2026-09-01  
**Version:** 0.2.1  
**Classification:** Internal Strategic Audit — Execution Mandate

---

## 🎯 Executive Verdict

### Execution update — 2026-09-03

The Phase 0 technical exit gate is now verified: the Cockpit generated real local media, enforced preview approval, supported owner-feedback retries, and published an approved private audio-derived video through the linked YouTube OAuth account. The earlier `$0` revenue finding remains valid because a private test upload is not revenue evidence. See `PRODUCTION_FINANCIAL_EXECUTION_REPORT_2026-09-03.md` for the evidence and remaining external gates.

| Metric | Value |
|--------|-------|
| **Current Revenue** | $0 (private test publishing verified; revenue not evidenced) |
| **Monthly Burn** | ~$20–30 (electricity only) |
| **Time to First Dollar** | 4–8 weeks (if Phase 0–1 complete) |
| **Stable Income Probability (12mo)** | **15–25%** (without fixes) → **60–75%** (with full execution) |
| **Fatal Blockers** | 2 (Provider-specific cloud media contracts, No audience acquisition) |
| **Investment Required** | ~$1,500 cash + 320h dev (Phases 0–3) |

**GO/NO-GO:** **GO** — Architecture is production-grade. Execution discipline is the only variable.

---

## 📋 Phase 0: FOUNDATION — UNBLOCK REVENUE (Week 1)
**Goal:** End-to-end publish working. Zero revenue → First dollar possible.

| ID | Task | Owner | Effort | Done Criteria |
|----|------|-------|--------|---------------|
| **P0-1** | Enable YouTube OAuth + test upload | SWE | 4h | Video appears on channel (unlisted) |
| **P0-2** | Set `YOUTUBE_UPLOAD_ENABLED=true` in `.env` | SWE | 15m | Config validated |
| **P0-3** | Enable `MUSIC_PUBLISH_ENABLED=true`, `PODCAST_PUBLISH_ENABLED=true` | SWE | 15m | Flags=true in config |
| **P0-4** | Fix `ProviderUnavailable` error handling in all engines | SWE | 8h | No unhandled exceptions in test run |
| **P0-5** | Run full pipeline end-to-end (research→publish) | SWE | 4h | Asset created, approved, published |

**Exit Gate:** `blue-waves review --last 1` shows published asset with YouTube URL.

---

## 📋 Phase 1: PROVIDER INTEGRATION — ENABLE SCALE (Weeks 2–3)
**Goal:** Cloud providers functional. Local-only → Hybrid routing working.

| ID | Task | Owner | Effort | Done Criteria |
|----|------|-------|--------|---------------|
| **P1-1** | Obtain aimlapi API key; implement `AimlapiMusicProvider.generate()` | SWE | 16h | Music generated via cloud |
| **P1-2** | Obtain KAI API key; implement `KaiMusicProvider.generate()` | SWE | 16h | Music generated via cloud |
| **P1-3** | Obtain Kling/Seedance API key; implement video providers | SWE | 24h | Video generated via cloud |
| **P1-4** | Configure SHIPO with real provider costs | SWE | 4h | `finance.py` shows real $/unit |
| **P1-5** | Test hybrid routing (local→cloud escalation) | SWE | 8h | Fallback works on local failure |
| **P1-6** | Produce 10 pieces using cloud providers | SWE | 20h | Assets in `data/` with cloud metadata |

**Exit Gate:** 10+ cloud-generated assets; SHIPO shows cost breakdown per provider.

---

## 📋 Phase 2: AUDIENCE ACQUISITION — GET VIEWS (Weeks 4–6)
**Goal:** Distribution automated. Publish → Views without manual work.

| ID | Task | Owner | Effort | Done Criteria |
|----|------|-------|--------|---------------|
| **P2-1** | Add SEO metadata to all content (titles, descriptions, tags) | SWE | 16h | YouTube upload includes optimized metadata |
| **P2-2** | Implement auto-short generation (60s clips from long-form) | SWE | 24h | Shorts uploaded alongside main |
| **P2-3** | Add podcast RSS feed generation | SWE | 12h | Valid RSS at `/feed.xml` |
| **P2-4** | Submit podcast to Apple/Spotify/Google | SWE | 4h | Listed in directories |
| **P2-5** | Implement analytics ingestion (YouTube API → `audience_metrics`) | SWE | 16h | `intelligence.py` receives real metrics |
| **P2-6** | Build content calendar / scheduler for consistency | SWE | 12h | 3+ publishes/week automated |

**Exit Gate:** 1,000+ views/mo; podcast in 3 directories; metrics flowing to KOYOSHU.

---

## 📋 Phase 3: OPTIMIZATION & LEARNING — IMPROVE MARGINS (Weeks 7–10)
**Goal:** Compound advantage. Data → Better content → Higher RPM → Lower CAC.

| ID | Task | Owner | Effort | Done Criteria |
|----|------|-------|--------|---------------|
| **P3-1** | Activate KOYOSHU: feed owner decisions back to agents | SWE | 16h | `intelligence.py` shows learning |
| **P3-2** | Activate SHIPO: weekly cost report + provider recommendations | SWE | 8h | Console shows "Switch to X saves $Y/mo" |
| **P3-3** | Build template library (5 video, 3 music, 2 podcast) | SWE | 24h | Templates selectable in Cockpit |
| **P3-4** | A/B test thumbnails/titles via Cockpit | SWE | 16h | CTR tracked per variant |
| **P3-5** | First sponsorship outreach (media kit + rates) | Owner | 8h | Response from 1+ brand |

**Exit Gate:** $300–$1,200/mo revenue; SHIPO optimizing spend; KOYOSHU improving hit rate.

---

## 📋 Phase 4: SAAS PIVOT EVALUATION — OPTIONAL SCALE (Weeks 8–14)
**Trigger:** Phase 3 hits **Base case** ($300/mo+ stable).  
**Kill:** <3 paying beta users after 4 weeks outreach.

| ID | Task | Owner | Effort | Done Criteria |
|----|------|-------|--------|---------------|
| **P4-1** | Design multi-tenant data model (orgs, workspaces, seats) | SWE | 24h | ER diagram + migration plan |
| **P4-2** | Implement auth (Clerk/Auth0) + org isolation | SWE | 40h | Multi-user login works |
| **P4-3** | Add Stripe billing (subscriptions, usage-based) | SWE | 24h | Checkout → active subscription |
| **P4-4** | Build onboarding wizard (connect providers, first content) | SWE | 32h | New user → published in <30min |
| **P4-5** | Recruit 5 beta users (creator communities) | Owner | 16h | 5 active paying beta users |
| **P4-6** | **GO/NO-GO Decision** | Owner | — | ≥3 paying users + positive NPS → continue |

---

## ⚰️ KILL CRITERIA (Non-Negotiable)

| Criterion | Threshold | Action |
|-----------|-----------|--------|
| Phase 0 incomplete | End of Week 2 | Sunset project; archive code |
| Phase 1 incomplete | End of Week 4 | Pivot to pure local tool; accept hobby status |
| <500 views/mo after 20 publishes | End of Month 3 | Abandon content path; evaluate SaaS only |
| Cloud cost > $200 with <$100 revenue | Any month | Hard stop on cloud; local-only mode |
| No beta users after 4 weeks SaaS outreach | End of Month 4 | Abandon SaaS; open-source core |

---

## 🔧 Technical Implementation Notes

### Key Files to Modify
| File | Phase | Purpose |
|------|-------|---------|
| `src/blue_waves/config.py` | 0 | Feature flags, provider keys |
| `src/blue_waves/providers.py` | 0,1 | Provider implementations, error handling |
| `src/blue_waves/connections.py` | 0 | YouTube OAuth flow |
| `src/blue_waves/music_engine.py` | 1 | Suno/ACE-Step routing |
| `src/blue_waves/video_engine.py` | 1 | Kling/Seedance routing |
| `src/blue_waves/podcast_engine.py` | 1 | Kokoro/Google TTS routing |
| `src/blue_waves/finance.py` | 1,3 | SHIPO cost tracking |
| `src/blue_waves/intelligence.py` | 2,3 | KOYOSHU learning, analytics ingestion |
| `src/blue_waves/service.py` | 2,3 | Cockpit API: RSS, Shorts, A/B, templates |
| `src/blue_waves/engines.py` | 3 | Template library integration |

### Environment Variables Required (`.env`)
```bash
# PUBLISHING (Phase 0)
YOUTUBE_UPLOAD_ENABLED=true
MUSIC_PUBLISH_ENABLED=true
PODCAST_PUBLISH_ENABLED=true

# PROVIDERS (Phase 1) — ADD REAL KEYS
AIMLAPI_API_KEY=your_key
AIMLAPI_BASE_URL=https://api.aimlapi.com/v1
KAI_API_KEY=your_key
KAI_BASE_URL=https://api.kai.ai/v1
KLING_API_KEY=your_key
KLING_BASE_URL=https://api.klingai.com/v1
SEEDANCE_API_KEY=your_key
SEEDANCE_BASE_URL=https://api.seedance.com/v1
KOKORO_API_KEY=your_key
KOKORO_BASE_URL=https://api.kokoro.dev/v1
GOOGLE_TTS_CREDENTIALS=path/to/sa.json

# COST CONTROL
BLUE_WAVES_MONTHLY_CLOUD_CENTS=5000  # $50/mo ceiling

# ANALYTICS (Phase 2)
YOUTUBE_API_KEY=your_key
POSTHOG_API_KEY=your_key  # optional
```

### Test Checklist for Phase 0 Completion
- [ ] `blue-waves health` → all green
- [ ] `blue-waves demo --type video --topic "test" --dry-run` → produces script
- [ ] `blue-waves demo --type music --topic "test" --dry-run` → produces music spec
- [ ] `blue-waves demo --type podcast --topic "test" --dry-run` → produces podcast spec
- [ ] `blue-waves cockpit` → dashboard loads at localhost:8420
- [ ] Manual approval in Cockpit → YouTube upload succeeds (unlisted)
- [ ] `blue-waves review --last 1` → shows published asset with metrics

---

## 📊 Success Metrics Dashboard (Track Weekly)

| Week | Metric | Target | Actual | Status |
|------|--------|--------|--------|--------|
| 1 | YouTube publish working | Yes/No | — | ⬜ |
| 1 | ProviderUnavailable fixed | 0 unhandled | — | ⬜ |
| 2 | Suno integration | Music generated | — | ⬜ |
| 3 | Kling/Seedance integration | Video generated | — | ⬜ |
| 3 | Kokoro/Google TTS | Podcast voices | — | ⬜ |
| 4 | SEO metadata on upload | 100% | — | ⬜ |
| 5 | Auto-Shorts generating | Yes/No | — | ⬜ |
| 5 | Podcast RSS live | Valid XML | — | ⬜ |
| 6 | Analytics flowing | Metrics in KOYOSHU | — | ⬜ |
| 6 | Weekly publishes | 3+ | — | ⬜ |
| 8 | Monthly revenue | $100+ | — | ⬜ |
| 10 | Monthly revenue | $300+ | — | ⬜ |
| 10 | SHIPO active | Recommendations visible | — | ⬜ |
| 10 | KOYOSHU active | Learning visible | — | ⬜ |

---

## 🏁 Sprint Rules (Ruthless Execution)

1. **One Phase at a Time** — No Phase 1 work until Phase 0 exit gate passed.
2. **Daily Commits** — Every task produces a commit. `git log --oneline` tells the story.
3. **No Feature Creep** — Only tasks in this document. New ideas → backlog.
4. **Metrics or It Didn't Happen** — Every claim backed by log output or screenshot.
5. **Kill Criteria Are Law** — Hit a threshold → execute the action. No negotiation.
6. **Owner Decisions Documented** — P0-5, P3-5, P4-6 require owner sign-off. Record in `DECISIONS.md`.

---

## 📝 Decision Log

| Date | Decision | Rationale | Author |
|------|----------|-----------|--------|
| 2026-09-01 | Begin Phase 0 execution | Audit complete; 3 fatal blockers identified | SWE |

---

**Next Action:** Phase 0 technical control-plane gates are complete. Enter the missing cloud provider API keys in the running Cockpit, then execute the owner-controlled production cohort (10-minute two-voice podcast, 2-minute pop-techno track, and 3-minute RTA contact-center video) with preview, rejection/retry, approval, and measured publish decisions.
