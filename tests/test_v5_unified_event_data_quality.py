from __future__ import annotations

from dataclasses import fields

import pytest

from hl_observer.data_contract.unified_event import EventReplayGuard, EventType, UnifiedEvent
from hl_observer.data_quality.gate_v5 import (
    DataQualityInput,
    DataQualityState,
    evaluate_campaign_data_quality,
)


def _event(**overrides) -> UnifiedEvent:
    base = dict(
        source="hyperliquid_ws",
        venue="hyperliquid",
        symbol_canonical="BTC",
        event_type=EventType.USER_FILL,
        exchange_ts_ms=1_000,
        recv_wall_ts_ms=1_010,
        recv_mono_ns=123_000_000,
        write_wall_ts_ms=1_012,
        event_id="fill-1",
        connection_id="conn-a",
        sequence=1,
        schema_version="v1",
        raw_evidence_ref="raw://fill-1",
    )
    base.update(overrides)
    return UnifiedEvent(**base)


def _quality(**overrides) -> DataQualityInput:
    base = dict(
        completeness=1.0,
        freshness_ms=100,
        max_freshness_ms=1_000,
        clock_skew_ms=10.0,
        max_clock_skew_ms=500.0,
        schema_valid=True,
        duplicate_count=0,
        gap_count=0,
        symbol_mapping_valid=True,
        source_provenance_present=True,
        days_covered=14,
        min_days_covered=14,
        coins_covered=3,
        min_coins_covered=3,
        wallets_vaults_covered=10,
        min_wallets_vaults_covered=10,
    )
    base.update(overrides)
    return DataQualityInput(**base)


def test_unified_event_has_all_v5_fields() -> None:
    assert {item.name for item in fields(UnifiedEvent)} == {
        "source",
        "venue",
        "symbol_canonical",
        "event_type",
        "exchange_ts_ms",
        "recv_wall_ts_ms",
        "recv_mono_ns",
        "write_wall_ts_ms",
        "event_id",
        "connection_id",
        "sequence",
        "schema_version",
        "raw_evidence_ref",
    }


def test_initial_ws_snapshot_is_state_evidence_not_economic_delta() -> None:
    event = _event(event_type=EventType.INITIAL_WS_SNAPSHOT)
    assert event.is_snapshot is True
    assert event.can_create_economic_delta is False


def test_reconnect_duplicate_and_restart_are_idempotent() -> None:
    guard = EventReplayGuard()
    original = _event()
    assert guard.observe(original).accepted
    reconnect_duplicate = _event(connection_id="conn-b", sequence=1)
    assert guard.observe(reconnect_duplicate).reason == "DUPLICATE_EVENT"
    restarted = EventReplayGuard(seen_keys=guard.seen_keys())
    assert restarted.observe(reconnect_duplicate).reason == "DUPLICATE_EVENT"


def test_sequence_gap_requires_explicit_reconciliation() -> None:
    guard = EventReplayGuard()
    assert guard.observe(_event()).accepted
    decision = guard.observe(_event(event_id="fill-3", sequence=3))
    assert decision.accepted is False
    assert decision.sequence_gap is True
    assert decision.reason == "SEQUENCE_GAP_RECONCILE_REQUIRED"


def test_out_of_order_is_fail_closed() -> None:
    guard = EventReplayGuard()
    assert guard.observe(_event(sequence=5)).accepted
    decision = guard.observe(_event(event_id="fill-4", sequence=4))
    assert decision.accepted is False
    assert decision.out_of_order is True


def test_missing_timestamp_is_not_replaced_with_now() -> None:
    with pytest.raises((TypeError, ValueError)):
        _event(exchange_ts_ms=None)


def test_data_quality_pass_requires_every_dimension() -> None:
    report = evaluate_campaign_data_quality(_quality())
    assert report.state is DataQualityState.PASS
    assert report.tradeable is True


def test_missing_provenance_or_measurement_is_blind() -> None:
    report = evaluate_campaign_data_quality(_quality(source_provenance_present=False))
    assert report.state is DataQualityState.BLIND
    assert report.tradeable is False
    assert "MISSING_SOURCE_PROVENANCE" in report.reasons


def test_conflict_stale_and_incomplete_are_distinct() -> None:
    assert evaluate_campaign_data_quality(_quality(clock_skew_ms=999)).state is DataQualityState.CONFLICTED
    assert evaluate_campaign_data_quality(_quality(freshness_ms=2_000)).state is DataQualityState.STALE
    assert evaluate_campaign_data_quality(_quality(days_covered=3)).state is DataQualityState.INCOMPLETE


def test_unknown_coverage_is_blind_not_zero() -> None:
    report = evaluate_campaign_data_quality(_quality(coins_covered=None))
    assert report.state is DataQualityState.BLIND
    assert "MISSING_COINS_COVERED" in report.reasons
