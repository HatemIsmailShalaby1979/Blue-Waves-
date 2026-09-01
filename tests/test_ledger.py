from blue_waves.ledger import AppendOnlyLedger


def test_hash_chain_is_intact(tmp_path):
    ledger = AppendOnlyLedger(tmp_path / "audit.jsonl")
    ledger.append("one", {"n": 1}, "bluewaves", "MIRA")
    ledger.append("two", {"n": 2}, "bluewaves", "ZACK")
    ok, message = ledger.verify()
    assert ok is True
    assert message == "hash chain intact"


def test_tampering_is_detected(tmp_path):
    ledger = AppendOnlyLedger(tmp_path / "audit.jsonl")
    ledger.append("one", {"n": 1}, "bluewaves", "MIRA")
    path = tmp_path / "audit.jsonl"
    text = path.read_text(encoding="utf-8").replace('"n": 1', '"n": 999')
    path.write_text(text, encoding="utf-8")
    ok, message = ledger.verify()
    assert ok is False
    assert "hash mismatch" in message
