from pathlib import Path

from blue_waves.config import Settings
from blue_waves.governance import Governance, Policy
from blue_waves.quality_gates import QualityGates


class Asset:
    status = "awaiting_owner"


def test_missing_probe_fields_are_not_accepted(monkeypatch, tmp_path):
    gates = QualityGates(Settings(data_dir=tmp_path), Governance(Policy()))
    media = tmp_path / "audio.wav"
    media.write_bytes(b"fixture")
    monkeypatch.setattr("blue_waves.quality_gates.probe_media", lambda toolchain, path: {
        "duration": 1.0,
        "sample_rate": 0,
        "channels": 0,
        "audio_codec": "pcm_s16le",
    })
    monkeypatch.setattr("blue_waves.quality_gates.measure_silence_ratio", lambda *args: 0.0)
    result = gates.check_media_asset(Asset(), str(media), "podcast")
    assert result.passed is False
    assert any("sample rate" in issue or "channel" in issue for issue in result.issues)
