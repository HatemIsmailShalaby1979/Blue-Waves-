from pathlib import Path

from blue_waves.enhancement import EnhancementResult, MediaEnhancer


def test_disabled_enhancement_copies_with_provenance(tmp_path):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"fixture")

    result = MediaEnhancer(enabled=False).master_audio(source, target)

    assert isinstance(result, EnhancementResult)
    assert target.read_bytes() == b"fixture"
    assert result.skipped == ["enhancement disabled"]
    assert result.input_sha256 == result.output_sha256
