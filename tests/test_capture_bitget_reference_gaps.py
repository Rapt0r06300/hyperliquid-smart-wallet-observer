"""Immutable Bitget REST reference-only gap receipts do not change replay status."""
from __future__ import annotations

import hashlib
import json

import pytest

from tools.capture_bitget_reference_gaps import (
    build_reference_gap_receipt, preserve_gap_receipt,
)


def _evidence():
    ident = "bitget-public-ws-trades-umausdt-demo"
    source = [{"trade_id": str(100+i), "exchange_ts_ms": 1000+i,
               "source": "BITGET_PUBLIC_REST_REFERENCE_ONLY",
               "raw_rest_row": {"tradeId": str(100+i), "symbol": "UMAUSDT",
                                "ts": str(1000+i), "price": "1.2", "size": "2"}}
              for i in range(6)]
    digest = hashlib.sha256(json.dumps(
        source, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()
    row = {
        "dataset_id": ident, "symbol": "UMAUSDT", "quality_status": "PARTIAL",
        "sha256": "a" * 64, "reconciliation": {"missing_from_live": 6},
    }
    inspection = {
        "dataset_id": ident, "catalog_index_sha256": "b" * 64,
        "logical_shard_sha256": "a" * 64, "byte_coverage_verified": True,
        "isolated_parse_chronology_compatible": True,
        "reclassified_safe": False, "replay_certified": False,
    }
    reference = {
        "status": "PARTIAL", "live_count": 53, "reference_count": 59,
        "missing_from_live": 6, "live_only": 0, "duplicate_live_keys": 0,
        "comparison_start_ts_ms": 1000,
        "comparison_end_ts_ms": 1099,
        "missing_reference_evidence": {
            "status": "REFERENCE_ONLY_NOT_MERGED_OR_REPLAY_CERTIFIED",
            "symbol": "UMAUSDT", "comparison_start_ts_ms": 1000,
            "comparison_end_ts_ms": 1099,
            "original_live_trade_count": 53,
            "missing_trade_count": 6, "rows": source,
            "rows_sha256": digest,
        },
    }
    return row, inspection, reference


def test_receipt_preserves_six_missing_rest_rows_without_promoting_original(tmp_path):
    row, inspected, reference = _evidence()
    result = build_reference_gap_receipt(row, inspected, reference)
    assert result["reference_missing_from_live_at_probe"] == 6
    assert result["original_missing_delta_matches_current_probe"] is True
    assert result["original_live_trade_count"] == 53
    assert result["status"] == "REFERENCE_ROWS_PRESERVED_NOT_REPLAY_CERTIFIED"
    assert result["reference_response_is_historical"] is True
    assert result["reclassified_safe"] is False
    assert result["validation_allowed"] is False
    assert result["all_missing_trade_records_recovered"] is False
    output = preserve_gap_receipt(tmp_path, result)
    assert json.loads(output.read_text()) == result
    with pytest.raises(ValueError, match="REFUSE_OVERWRITE"):
        preserve_gap_receipt(tmp_path, result)


def test_receipt_refuses_mismatched_count_sha_and_incomplete_reconciliation():
    row, inspected, reference = _evidence()
    reference["missing_reference_evidence"]["rows"][0]["raw_rest_row"]["price"] = "3"
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        build_reference_gap_receipt(row, inspected, reference)
    row, inspected, reference = _evidence()
    reference["missing_from_live"] = 5
    with pytest.raises(ValueError, match="COUNT_MISMATCH"):
        build_reference_gap_receipt(row, inspected, reference)
    row, inspected, reference = _evidence()
    reference["live_only"] = 1
    with pytest.raises(ValueError, match="INCOMPLETE"):
        build_reference_gap_receipt(row, inspected, reference)
    row, inspected, reference = _evidence()
    inspected["byte_coverage_verified"] = False
    with pytest.raises(ValueError, match="NOT_BYTE_VERIFIED"):
        build_reference_gap_receipt(row, inspected, reference)


def test_rest_reference_is_never_a_synthetic_live_event():
    row, inspected, reference = _evidence()
    proof = build_reference_gap_receipt(row, inspected, reference)
    assert proof["source_category"] == "PUBLIC_REST_REFERENCE_NOT_LIVE_WEBSOCKET"
    assert proof["original_quality_status"] == "PARTIAL"
    assert len(proof["reference_only_rows"]) == 6
    assert proof["reference_trade_count_at_probe"] == 59
    assert proof["replay_certified"] is False
    assert proof["proof_of_pnl_allowed"] is False
    assert row["quality_status"] == "PARTIAL"
