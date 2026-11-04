from __future__ import annotations

from hl_observer.collection.archive_s3 import compare_archive_native_coverage
from hl_observer.collection.collecte_fiable import reconnect_recovery_plan
from hl_observer.collection.copy_vault_checkpoint_tail import coverage_receipt
from hl_observer.collection.hyperliquid_clock_sync import classify_clock_skew
from hl_observer.collection.l2_snapshot_cache import causal_snapshot_allowed
from hl_observer.collection.market_capture_tiers import classify_l2_frequency
from hl_observer.collection.shard_writer import hash_transformation_receipt
from hl_observer.collection.userfills_live import build_receive_time_evidence
from hl_observer.collection.verrou_instance import lease_conflict_receipt
from hl_observer.collection.weight_budgeter import merge_readonly_budget_plans


def test_eco_011_checkpoint_coverage_requires_exact_counts() -> None:
    result = coverage_receipt({"complete_lines": 10, "checkpoints_captured": 2, "reconnect_backfill_blocked": 0, "invalid_rejected": 0}, expected_lines=10)
    assert result["status"] == "PROVEN"


def test_eco_012_receive_clock_and_native_identity_are_preserved() -> None:
    result = build_receive_time_evidence({"time": 100, "received_at_ms": 110, "hash": "native-1"})
    assert result["status"] == "PROVEN"


def test_eco_013_clock_skew_is_measured() -> None:
    assert classify_clock_skew({"clock_offset_ms": 20}, max_abs_skew_ms=50)["status"] == "PROVEN"
    assert classify_clock_skew({"clock_offset_ms": 100}, max_abs_skew_ms=50)["status"] == "REJECTED"


def test_eco_014_reconnect_requires_backfill_evidence() -> None:
    result = reconnect_recovery_plan(last_seen_ts_ms=100, reconnect_ts_ms=200, backfill_available=True)
    assert result["status"] == "BACKFILL_REQUIRED"
    assert reconnect_recovery_plan(last_seen_ts_ms=100, reconnect_ts_ms=200, backfill_available=False)["status"] == "UNMEASURABLE"


def test_eco_015_rest_and_ws_budget_share_the_tightest_bound() -> None:
    result = merge_readonly_budget_plans({"remaining": 10}, {"remaining": 4})
    assert result["status"] == "PROVEN"
    assert result["shared_remaining"] == 4


def test_eco_016_active_lease_blocks_second_worker() -> None:
    result = lease_conflict_receipt({"run_id": "owner", "heartbeat_ms": 900}, {"run_id": "other"}, now_ms=950, ttl_ms=100)
    assert result["status"] == "CONFLICT"


def test_eco_017_raw_and_transformed_hashes_are_bound() -> None:
    result = hash_transformation_receipt(b"raw", b"transformed", source="SAFE")
    assert result["status"] == "PROVEN"
    assert result["raw_sha256"] != result["transformed_sha256"]


def test_eco_018_l2_frequency_uses_observed_timestamps() -> None:
    result = classify_l2_frequency([1000, 1100, 1200], max_interval_ms=150)
    assert result["status"] == "PROVEN"


def test_eco_019_book_received_after_signal_is_no_trade() -> None:
    result = causal_snapshot_allowed(snapshot_ts_ms=100, received_ts_ms=120, signal_ts_ms=110)
    assert result["status"] == "NO_TRADE"


def test_eco_020_archive_and_native_coverage_are_compared() -> None:
    result = compare_archive_native_coverage({"events": 2, "fills": 3, "l2": 4}, {"events": 1, "fills": 3, "l2": 2})
    assert result["status"] == "PROVEN"
    assert result["deltas"] == {"events": 1, "fills": 0, "l2": 2}
