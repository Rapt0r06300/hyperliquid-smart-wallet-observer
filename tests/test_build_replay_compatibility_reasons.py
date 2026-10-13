"""The canonical replay-reason receipt must never balloon into >100 MiB."""
import hashlib
import json
import sys

from tools import build_replay_compatibility_reasons as reasons


def test_exact_aggregates_without_repeating_all_index_rows(tmp_path, monkeypatch):
    source = tmp_path / "DATA_INDEX.json"
    source.write_text('{"catalog":"test"}', encoding="utf-8")
    output = tmp_path / "REPLAY_COMPATIBILITY_REASONS.json"
    rows = [
        {
            "dataset_id": f"safe-{i}", "quality_status": "SAFE",
            "replay_compatible": True, "family": "trades",
            "trade_count_exact": True, "trade_count": 3,
        }
        for i in range(12000)
    ]
    rows.extend([
        {
            "dataset_id": "partial", "quality_status": "PARTIAL",
            "replay_compatible": False, "family": "trades",
            "trade_count_exact": True, "trade_count": 5,
            "quality_reasons": ["RECONCILIATION_UNVERIFIED"],
        },
        {
            "dataset_id": "reject", "quality_status": "REJECT",
            "replay_compatible": False, "family": "trades",
            "trade_count_exact": True, "trade_count": 7,
            "quality_reasons": ["FATAL_INTEGRITY:gap_count=1"],
        },
    ])
    monkeypatch.setattr(reasons, "INDEX", source)
    monkeypatch.setattr(reasons, "read_index", lambda _path: {"shards": rows})
    monkeypatch.setattr(sys, "argv", ["reasons", "--output", str(output)])
    assert reasons.main() == 0
    body = json.loads(output.read_text(encoding="utf-8"))
    assert body["schema"] == "alina.replay_compatibility_reasons.v3"
    assert body["row_count"] == 12002
    assert body["source_index_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert body["replayable_trade_count_exact"] == 36000
    assert body["non_replayable_trade_count_exact"] == 12
    assert body["reason_counts"]["SAFE_REPLAY_COMPATIBLE"] == 12000
    assert body["blocking_reason_shard_counts"]["RECONCILIATION_UNVERIFIED"] == 1
    assert body["blocking_reason_trade_counts"]["FATAL_INTEGRITY:gap_count=1"] == 7
    assert body["safe_not_replayable_count"] == 0
    assert body["replayable_not_safe_count"] == 0
    assert "classifications" not in body
    assert body["classifications_materialized"] is False
    assert output.stat().st_size < 8192
    signed = {k: v for k, v in body.items() if k != "receipt_digest"}
    assert body["receipt_digest"] == hashlib.sha256(
        reasons.canonical(signed).encode()
    ).hexdigest()


def test_safe_rows_never_require_manifest_io(tmp_path, monkeypatch):
    monkeypatch.setattr(reasons, "ROOT", tmp_path)
    assert reasons._blocking_reasons({
        "quality_status": "SAFE", "replay_compatible": True,
        "manifest_path": "missing.json",
    }) == []


def test_invalid_row_fails_closed_without_overwriting_previous_receipt(tmp_path, monkeypatch):
    src = tmp_path / "DATA_INDEX.json"
    src.write_text("[]", encoding="utf-8")
    dest = tmp_path / "REPLAY_COMPATIBILITY_REASONS.json"
    dest.write_text("previous certified receipt", encoding="utf-8")
    monkeypatch.setattr(reasons, "INDEX", src)
    monkeypatch.setattr(reasons, "read_index", lambda _p: {"shards": [None]})
    monkeypatch.setattr(sys, "argv", ["reasons", "--output", str(dest)])
    import pytest
    with pytest.raises(ValueError, match="INVALID_CANONICAL_SHARD_ROW"):
        reasons.main()
    assert dest.read_text(encoding="utf-8") == "previous certified receipt"
