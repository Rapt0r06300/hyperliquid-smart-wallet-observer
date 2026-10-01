from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from manifest_policy import classify_manifest, verify_asset  # noqa: E402


def manifest() -> dict:
    return {
        "dataset_id": "bybit-btc-l2-1000-2000",
        "family": "l2",
        "venue": "bybit",
        "symbol": "BTCUSDT",
        "start_ts_ms": 1000,
        "end_ts_ms": 2000,
        "sha256": "a" * 64,
        "bytes": 123,
        "event_count": 50,
        "trade_count": 50,
        "trade_count_exact": True,
        "unique_trade_count": 50,
        "unique_trade_count_exact": True,
        "collector_version": "abc123",
        "source": "bybit_public_ws",
        "quality_status": "PARTIAL",
        "release_asset": "bybit-btc-l2-1000-2000.jsonl.gz",
        "asset_verified": True,
        "replay_compatible": True,
        "replay_schema_version": "alina.replay.v1",
        "replay_reason": "SMOKE_OK",
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
        },
        "integrity": {
            "gap_count": 0,
            "duplicate_count": 0,
            "regression_count": 0,
            "missing_timestamp_count": 0,
            "missing_monotonic_count": 0,
            "desync_count": 0,
            "duplicates_deduped": True,
        },
        "reconciliation": {"status": "MATCHED"},
        "required_channels": ["l2Book"],
        "observed_channels": ["l2Book"],
        "cost_model": {"applicable": False, "ready": False},
    }


def test_complete_manifest_is_safe() -> None:
    status, reasons = classify_manifest(manifest())
    assert status == "SAFE"
    assert reasons == []


def test_gap_is_rejected() -> None:
    value = manifest()
    value["integrity"]["gap_count"] = 1
    status, reasons = classify_manifest(value)
    assert status == "REJECT"
    assert any(reason.startswith("FATAL_INTEGRITY:gap_count") for reason in reasons)


def test_unverified_reconciliation_is_never_safe() -> None:
    value = manifest()
    value["reconciliation"] = {"status": "UNVERIFIED"}
    status, reasons = classify_manifest(value)
    assert status == "PARTIAL"
    assert "RECONCILIATION_UNVERIFIED" in reasons


def test_unverified_asset_is_never_safe() -> None:
    value = manifest()
    value["asset_verified"] = False
    status, reasons = classify_manifest(value)
    assert status == "PARTIAL"
    assert "ASSET_NOT_VERIFIED" in reasons


def test_verify_asset_checks_size_and_sha256(tmp_path) -> None:
    path = tmp_path / "shard.jsonl.gz"
    path.write_bytes(b"real shard bytes")
    value = manifest()
    value["bytes"] = path.stat().st_size
    value["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert verify_asset(value, path) == (True, "MATCHED")

    path.write_bytes(b"tampered")
    assert verify_asset(value, path)[0] is False


def test_cost_model_blocks_safe_only_when_applicable() -> None:
    value = manifest()
    value["cost_model"] = {"applicable": True, "ready": False}
    assert classify_manifest(value)[0] == "PARTIAL"
    value["cost_model"]["ready"] = True
    assert classify_manifest(value)[0] == "SAFE"


def test_l2_websocket_continuity_can_be_safe() -> None:
    value = manifest()
    value["family"] = "l2Book"
    value["provenance"]["transports"] = ["websocket"]
    value["reconciliation"] = {"status": "SOURCE_CONTINUITY_VERIFIED"}
    status, reasons = classify_manifest(value)
    assert status == "SAFE"
    assert reasons == []


def test_trade_requires_matched_reconciliation() -> None:
    value = manifest()
    value["family"] = "trades"
    value["provenance"]["transports"] = ["websocket"]
    value["reconciliation"] = {"status": "SOURCE_CONTINUITY_VERIFIED"}
    status, reasons = classify_manifest(value)
    assert status == "PARTIAL"
    assert "RECONCILIATION_MATCH_REQUIRED" in reasons

    value["reconciliation"] = {"status": "MATCHED"}
    assert classify_manifest(value)[0] == "SAFE"


def test_http_snapshot_can_use_snapshot_verified() -> None:
    value = manifest()
    value["family"] = "open_interest"
    value["provenance"]["transports"] = ["https"]
    value["reconciliation"] = {"status": "SNAPSHOT_VERIFIED"}
    assert classify_manifest(value)[0] == "SAFE"


def _event_contract() -> dict:
    return {
        "schema": "alina.event_intelligence_integration.v1",
        "idea_count": 120,
        "coverage_complete": True,
        "coverage_sha256": "c" * 64,
        "linked_strategy_families": [
            "arbitrage",
            "copy_vault",
            "cross_venue_dislocation",
            "lead_lag",
        ],
        "dataset_families": ["external_events"],
        "proof_state": "STRUCTURAL_ONLY",
        "proof_of_pnl_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


def test_external_events_require_the_complete_120_idea_binding() -> None:
    value = manifest()
    value["family"] = "external_events"
    value["provenance"]["transports"] = ["https"]
    value["reconciliation"] = {
        "status": "UNAVAILABLE",
        "reason": "NO_INDEPENDENT_EXACT_REFERENCE",
    }
    value["event_intelligence"] = _event_contract()

    status, reasons = classify_manifest(value)
    assert status == "PARTIAL"
    assert "RECONCILIATION_UNAVAILABLE" in reasons

    del value["event_intelligence"]
    status, reasons = classify_manifest(value)
    assert status == "REJECT"
    assert "MISSING:event_intelligence" in reasons


def test_external_event_binding_cannot_claim_pnl_or_omit_a_module() -> None:
    value = manifest()
    value["family"] = "external_events"
    value["reconciliation"] = {"status": "UNAVAILABLE"}
    value["event_intelligence"] = _event_contract()
    value["event_intelligence"]["proof_of_pnl_allowed"] = True
    value["event_intelligence"]["linked_strategy_families"].remove("copy_vault")

    status, reasons = classify_manifest(value)
    assert status == "REJECT"
    assert "INVALID:event_intelligence" in reasons


def test_external_event_runtime_requires_all_bound_evidence_receipts() -> None:
    value = manifest()
    value["family"] = "external_events"
    value["provenance"]["transports"] = ["https"]
    value["reconciliation"] = {
        "status": "UNAVAILABLE",
        "reason": "NO_INDEPENDENT_EXACT_REFERENCE",
    }
    value["event_intelligence"] = _event_contract()
    value["event_intelligence_runtime"] = {
        "schema": "alina.event_intelligence_runtime_evidence.v1",
        "runtime_evidence_sha256": "a" * 64,
        "accepted_event_count": 4,
        "economic_research_sha256": "b" * 64,
        "economic_research_state": "UNMEASURABLE",
        "market_response_sha256": "c" * 64,
        "market_response_state": "UNMEASURABLE",
        "research_protocol_sha256": "d" * 64,
        "research_protocol_state": "UNMEASURABLE",
        "proof_state": "STRUCTURAL_ONLY",
        "proof_of_pnl_allowed": False,
    }
    status, reasons = classify_manifest(value)
    assert status == "PARTIAL"
    assert "EVENT_INTELLIGENCE_RUNTIME_EVIDENCE_INVALID" not in reasons

    del value["event_intelligence_runtime"]["economic_research_sha256"]
    status, reasons = classify_manifest(value)
    assert status == "PARTIAL"
    assert "EVENT_INTELLIGENCE_RUNTIME_EVIDENCE_INVALID" in reasons
