<div align="center">

# Blue Waves


<!-- badges:start -->

[![CI](https://github.com/HatemIsmailShalaby1979/Blue-Waves-/actions/workflows/Python%20application/badge.svg)](https://github.com/HatemIsmailShalaby1979/Blue-Waves-/actions)
![licence](https://img.shields.io/badge/licence-MIT-blue)
[![last commit](https://img.shields.io/github/last-commit/HatemIsmailShalaby1979/Blue-Waves-)](https://github.com/HatemIsmailShalaby1979/Blue-Waves-/commits/main)
![status](https://img.shields.io/badge/ci-in_progress-lightgrey?label=in_progress%20(2026-10-05))

*Measured 2026-10-06 — CI **in_progress**; head `c29db4c` (2026-10-05); Python.*

<!-- No static test or coverage count is shown here: a frozen
     number decays silently. Run the suite for a current figure;
     the CI badge above is the live status. -->
<!-- badges:end -->

**A multi-format content studio and the first commercial vertical on Helix Codex.**

![Status](https://img.shields.io/badge/status-pre--revenue-yellow)
![Pylint](https://github.com/HatemIsmailShalaby1979/Blue-Waves-/actions/workflows/pylint.yml/badge.svg)
![Python application](https://github.com/HatemIsmailShalaby1979/Blue-Waves-/actions/workflows/python-app.yml/badge.svg)
![Licence](https://img.shields.io/badge/licence-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.12-3776ab)

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
with scopes `youtube.upload`, `yt-analytics.readonly`, and `youtube.force-ssl` (the
force-ssl scope is what the privacy flip to public requires). Unapproved media stays in the
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

- `cockpit_ui.py` — 12 navigation panels showing quality metrics, approval status, audit chain.
- Scheduler — `tick()` / `run_automated_cycle()`: queue, generate, quality gate, `awaiting_owner`, retries up to 3, ledger-logged.
- Quality gates — `ffprobe` + FFT + LUFS + silence, hard thresholds.
- Provider rotation — local plus cloud-ready; cloud providers fail closed until approved.
- `audit_events` — hash-chained audit trail; every external action consent-gated.
- SHEPO finance — SHEPO is the finance agent of record: real per-provider costs, CPM projection, break-even, provider ROI.

## Cockpit

The approval queue with a held asset: the owner reviews a real preview before approving or
rejecting, and nothing publishes until the owner approves. The capture is from a local
cockpit instance with a demo asset.

![Blue Waves cockpit — pending approval queue with a held asset](docs/cockpit-approvals.png)

## Production status & test coverage

Stated plainly and dated. This section is last by design. The Snapshot column is the
date that row's evidence was last captured; rows that were not re-measured keep their
original date.

| Evidence | Value | Snapshot |
|---|---|---|
| Tests | 167 passed across sequential chunks (151 project + 16 vendored; re-measured 2026-10-02) — the YouTube external-video publish feature added 38 project tests, and 3 more cover the Ken Burns render paths. Cockpit E2E flake addressed (client HTTP timeout 30s → 180s) | 2026-10-02 |
| CI (GitHub Actions) | **Green** on `main` — `Pylint` (run 36946472204) and `Python application` (run 36946472214) both pass at `bbc3b56`, 2026-10-02 | 2026-10-02 |
| YouTube OAuth | Complete, client configured, test user active | 2026-09-05 |
| End-to-end video publish | Implemented; upload path exercised once (video NHXdNQzF5m0, 2026-09-05). Public visibility not verified: oEmbed returns 403 (re-checked 2026-09-30). | 2026-09-05; re-checked 2026-09-30 |
| Podcast RSS | Valid, iTunes-compatible RSS 2.0 | 2026-09-05 |
| Quality gates | `ffprobe` + FFT + LUFS + silence, hard thresholds | 2026-09-05 |
| SHEPO finance | Real per-provider costs, CPM projection, break-even, provider ROI | 2026-09-05 |
| Version | v0.3.0 (`pyproject.toml`, `src/blue_waves/__init__.py`) | 2026-10-01 |

> [!WARNING]
> Revenue is **$0**. The studio is pre-revenue; the SHEPO projection is a model, not a receipt. The container image has **never been built** — the repository contains no `Dockerfile` (checked 2026-10-01: `docker build .` fails with `open Dockerfile: no such file or directory`, and the Docker daemon itself is available), so static packaging tests cover the surface. Nine production-only gates remain red by design (no certified data isolation, no external observer audit, no legal privacy review — the nine are enumerated in `docs/SECURITY_REVIEW.md`). No external audit, no signed security review, no assigned on-call owner. GitHub Actions CI is **green** on `main` (runs 36946472204 / 36946472214, `bbc3b56`, 2026-10-02); the badges above are live and show that state.

## Run it

Requires Python 3.10+ and ffmpeg on PATH (local mastering). Install the package
itself — there is no `requirements.txt`; `pyproject.toml` is the dependency source
of truth:

```bash
pip install -e .

# Governed CLI (console script installed by the package):
blue-waves --help
blue-waves preflight --video /path/to/video.mp4

# Same CLI via the module entry point:
python -m blue_waves --help

# Cockpit web UI (serves http://127.0.0.1:8420):
python start_cockpit.py
```

Provider APIs (Suno, ElevenLabs, Kling, Seedance) and YouTube OAuth credentials are
required for generation and publish; local mastering needs ffmpeg. Untracked planning
documents (`docs/FREE_PROVIDER_KEYS.md`, `docs/WINNER_OPTIMIZATION_PLAN.md`) are not
part of the repository and their claims are not counted here.

## Related work

- [Portfolio](https://github.com/HatemIsmailShalaby1979/HatemIsmailShalaby1979) — how this project fits the wider work

## Author

Built by Hatem Ismail Shalaby, Contact Centre Operations & AI Implementation Lead | WFM & CX Transformation. Background: https://github.com/HatemIsmailShalaby1979

## Licence

MIT
