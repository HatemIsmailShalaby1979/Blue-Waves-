<div align="center">

# Blue Waves

**A multi-format content studio and the first commercial vertical on Helix Codex.**

![Status](https://img.shields.io/badge/status-pre--revenue-yellow)
![Tests](https://img.shields.io/badge/tests-125%20collected-2ea043)
![Licence](https://img.shields.io/badge/licence-MIT-blue)
![Python](https://img.shields.io/badge/python-3.12%2B-3776ab)

</div>

## One-line identity

Blue Waves is a multi-format content studio — video, music, and podcasts — and the
first commercial vertical built on the Helix Codex framework. It produces through a
hybrid local/cloud pipeline that stays under the owner's control.

> [!NOTE]
> **Operating principle.** No agent approves its own publish. Every output passes real quality measurements (`ffprobe`, LUFS, FFT, silence detection) before the owner is even asked, and the default is hold. The owner sees exactly what will go out; an unapproved asset stays in the library with a hash-chained audit trail. External actions need the owner's consent — cloud providers fail closed until approved.

## What it does

**Create.** Local generation first (Ken Burns 1080p video, Suno music, ElevenLabs TTS
podcast), with cloud-ready paths (Kling and Seedance video, an ACE-Step local fallback)
and an FFmpeg-first mastering layer. Provider rotation is quota-aware.

**Gate.** Every output passes real quality proxies before approval is considered:

| Medium | Gate |
|---|---|
| Video | 1080p, 30fps, h264, verified by `ffprobe` |
| Music and video audio | 48kHz stereo, -14 LUFS |
| Podcast audio | 48kHz stereo, -16 LUFS |
| All audio | Silence detection and FFT checks |

Approval is blocked if the preview is missing, empty, or below gate.

**Publish or hold.** Approved media moves through the Cockpit. YouTube OAuth is complete
with scopes `youtube.upload` and `yt-analytics.readonly`. Unapproved media stays in the
library with a hash-chained audit trail in `audit_events`. The default is hold. No agent
approves its own publish.

## How it fits Helix Codex

Blue Waves is a **vertical** — the first commercial line built on the Helix Codex
framework. Unlike the component repositories, it **consumes Helix Prime as a live
external client** over the framework's contracts: never embedded, never silent. Helix
Prime remains the same six-engine platform with nine agents, governed memory, and audit
chains, and it remains pre-pilot. The code relationship is a dependency on the
framework's governance contract, with an independent runtime — not shared source.

## Architecture

- `cockpit_ui.py` — 11 navigation panels showing quality metrics, approval status, audit chain.
- Scheduler — `tick()` / `run_automated_cycle()`: queue, generate, quality gate, `awaiting_owner`, retries up to 3, ledger-logged.
- Quality gates — `ffprobe` + FFT + LUFS + silence, hard thresholds.
- Provider rotation — local plus cloud-ready; cloud providers fail closed until approved.
- `audit_events` — hash-chained audit trail; every external action consent-gated.
- SHEPO finance — SHEPO is the finance agent of record: real per-provider costs, CPM projection, break-even, provider ROI.

## Production status & test coverage

Stated plainly and dated. This section is last by design.

| Evidence | Value | Snapshot |
|---|---|---|
| Tests | 125 collected (109 project + 16 vendored); all 109 project tests pass; one cockpit E2E test intermittently order-dependent | 2026-09-27 |
| YouTube OAuth | Complete, client configured, test user active | 2026-09-05 |
| End-to-end video publish | Verified (`NHXdNQzF5m0`) | 2026-09-05 |
| Podcast RSS | Valid, iTunes-compatible RSS 2.0 | 2026-09-05 |
| Quality gates | `ffprobe` + FFT + LUFS + silence, hard thresholds | 2026-09-05 |
| SHEPO finance | Real per-provider costs, CPM projection, break-even, provider ROI | 2026-09-05 |
| Version | v0.3.0 | 2026-09-05 |

> [!WARNING]
> Revenue is **$0**. The studio is pre-revenue; the SHEPO projection is a model, not a receipt. The container image has **never been built** — the sandbox Docker daemon was unavailable during validation, so static packaging tests cover the surface. Nine production-only gates remain red by design (no certified data isolation, no external observer audit, no legal privacy review — the nine are enumerated in `docs/SECURITY_REVIEW.md`). No external audit, no signed security review, no assigned on-call owner. Earlier revisions of this file said 85 tests, which understated it; the 125 figure is the current collection.

## Run it

```bash
pip install -r requirements.txt
python cockpit_ui.py
```

Provider APIs (Suno, ElevenLabs, Kling, Seedance) and YouTube OAuth credentials are
required for generation and publish; local mastering needs ffmpeg. Untracked planning
documents (`docs/FREE_PROVIDER_KEYS.md`, `docs/WINNER_OPTIMIZATION_PLAN.md`) are not
part of the repository and their claims are not counted here.

## Related work

- [Helix Prime](https://github.com/HatemIsmailShalaby1979/Helix-Prime) — the operations core
- [Helix Education](https://github.com/HatemIsmailShalaby1979/Helix-Education) — event-sourced learning engine
- [Study Studio](https://github.com/HatemIsmailShalaby1979/Study-Studio) — local-first AI tutor
- [L&D Command Center](https://github.com/HatemIsmailShalaby1979/L-D-Command-Center) — desktop learning and career workstation
- [LIVE Support Assistant](https://github.com/HatemIsmailShalaby1979/LIVE-Support-Assistant) — explainable support prototype
- [Full portfolio](https://github.com/HatemIsmailShalaby1979) — how this project fits the wider work

### The 2026 building attempts

- [WFM Forecasting Calculator](https://github.com/HatemIsmailShalaby1979/wfm-forecasting-calculator)
- [RTA Command Center](https://github.com/HatemIsmailShalaby1979/RTA_command_center)
- [CX Sentiment Sentinel](https://github.com/HatemIsmailShalaby1979/cx-sentiment-sentinel)
- [Dynamic Ops Automation Engine](https://github.com/HatemIsmailShalaby1979/Dynamic-Ops-Automation-Engine)

## Author

**Hatem Ismail Shalaby** — Operations Architect · AI Systems Engineer · Founder

- GitHub: [HatemIsmailShalaby1979](https://github.com/HatemIsmailShalaby1979)
- LinkedIn: [hatem-shalaby-202902127](https://www.linkedin.com/in/hatem-shalaby-202902127/)
- Email: hatemshalaby2025@gmail.com
- Education: BSc Managerial Sciences (Computer Section), Sadat Academy for Management Sciences; Business Analytics Nanodegree, Udacity

Based in Al Obour City, Al-Qalyubia Governorate, Egypt.

## Licence

MIT
