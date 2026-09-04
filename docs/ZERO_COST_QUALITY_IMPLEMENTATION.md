# Blue Waves Zero-Cost Quality Implementation

This document records the implemented three-layer transformation derived from the zero-cost media research.

## Layer 1: Provider rotation and quota safety

- `src/blue_waves/provider_rotation.py` provides a persisted, thread-safe rotation matrix.
- Providers declare capability metadata: content type, local/cloud mode, free-tier status, quota units, estimated cents, quality rank, and commercial-use status.
- Generation reserves capacity before calling a provider and releases it when a request fails.
- Daily and monthly usage resets are clock-aware and persisted under the configured data directory.
- Unknown or paid cloud capacity is not treated as guaranteed free. Paid capacity requires a positive monthly budget and owner approval.
- High/premium requests prefer eligible high-quality providers; free/draft requests prefer free-tier/local providers. The monthly budget is resolved against the first eligible route, so zero-budget high-quality requests can still succeed through validated local/free fallbacks.
- The research report's third-party quota numbers are not hardcoded as facts; they must be configured and verified by the owner.

## Layer 2: Open-source/free-GPU boundary

The codebase keeps free-GPU and consumer-web automation out of the synchronous provider path. Those services are not stable request/response APIs and may have changing terms, watermarks, or commercial restrictions. `src/blue_waves/cloud_gpu_orchestrator.py` now defines a persisted asynchronous job contract with explicit submit, poll, cancel, unknown-outcome, artifact-download, checksum, and validation states. Platform-specific adapters remain opt-in; no unverified API contract is fabricated.

## Layer 3: Enhancement and perceptual proxy gates

- `src/blue_waves/enhancement.py` adds FFmpeg-first audio mastering and video mastering.
- Every generated music, podcast, and video asset records distinct source/output paths, hashes, configured profile, steps, and skipped/error states.
- Audio is resampled to 48 kHz stereo, loudness normalized, and true-peak limited.
- Video is normalized to 720p-or-better delivery dimensions, 24 fps, H.264, fast-start output, and the shared audio delivery spec.
- Quality gates now inspect frame rate and unusually low video bitrate in addition to existing structural and silence checks, require the expected media stream type, and reject missing audio sample-rate/channel metadata.
- Music and podcast convenience checks no longer auto-approve merely because a provider happens to be free. Owner review remains required.

## Validation

Run:

```bash
python -m pytest tests -q
```

Live provider checks remain opt-in. Test doubles and the rotation/enhancement unit tests are deterministic and do not spend external quota.
