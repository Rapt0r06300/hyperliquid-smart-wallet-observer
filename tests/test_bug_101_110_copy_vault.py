from __future__ import annotations

import pytest

from hl_observer.core.causal_time import (
    CausalTimestamp,
    bounded_asof_match,
    causal_clock_skew_ms,
    causal_event_admission,
    causal_timestamp_from_record,
    parse_utc_epoch_ms,
    compare_monotonic_within_connection,
)
from hl_observer.data_contract.timestamp_unit_validator import detecter_unite, normaliser_ms, valider
from hl_observer.feed_integrity.causal_snapshot_delta_persist import DELTA, SNAPSHOT, PersistanceCausale


def test_bug101_exchange_event_after_receive_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        CausalTimestamp(1_001, 1_000, None, 1_000)


def test_bug102_ambiguous_seconds_are_not_normalized_as_milliseconds() -> None:
    result = normaliser_ms(1_700_000_000)
    assert result["conforme"] is False
    assert result["timestamp_ms"] is None
    assert normaliser_ms(1_700_000_000, allow_relative=True)["timestamp_ms"] == 1_700_000_000


def test_bug103_microseconds_are_not_treated_as_milliseconds() -> None:
    assert detecter_unite(1_700_000_000_000_000) == "us"
    assert valider(1_700_000_000_000_000, unite_attendue="ms")["conforme"] is False


def test_bug104_clock_skew_is_measured_only_from_two_real_clocks() -> None:
    assert causal_clock_skew_ms(exchange_ts_ms=900, receive_ts_ms=1_000) == 100
    assert causal_clock_skew_ms(exchange_ts_ms=None, receive_ts_ms=1_000) is None


def test_bug105_unknown_skew_is_not_replaced_with_zero() -> None:
    assert causal_clock_skew_ms(exchange_ts_ms="bad", receive_ts_ms=1_000) is None


def test_bug106_event_at_decision_is_admitted_but_future_event_is_not() -> None:
    assert causal_event_admission(event_ts_ms=1_000, receive_ts_ms=1_000, decision_ts_ms=1_000)["status"] == "PROVEN"
    assert causal_event_admission(event_ts_ms=1_001, receive_ts_ms=1_001, decision_ts_ms=1_000)["reason"] == "EVENT_AFTER_DECISION"


def test_bug107_equal_timestamps_have_a_stable_event_id_tiebreaker() -> None:
    left = CausalTimestamp(None, 1_000, 10, 1_000, event_id="a")
    right = CausalTimestamp(None, 1_000, 10, 1_000, event_id="b")
    assert left.stable_order_key() < right.stable_order_key()


def test_bug108_feature_cutoff_rejects_post_cutoff_event() -> None:
    result = causal_event_admission(
        event_ts_ms=1_001,
        receive_ts_ms=1_001,
        decision_ts_ms=2_000,
        feature_cutoff_ts_ms=1_000,
    )
    assert result["status"] == "NO_TRADE"
    assert result["reason"] == "EVENT_AFTER_CUTOFF"


def test_bug109_asof_join_has_a_finite_backward_tolerance() -> None:
    assert bounded_asof_match(event_ts_ms=1_000, candidate_ts_ms=900, tolerance_ms=100)["status"] == "PROVEN"
    assert bounded_asof_match(event_ts_ms=1_000, candidate_ts_ms=1_001, tolerance_ms=100)["reason"] == "CANDIDATE_AFTER_EVENT"
    assert bounded_asof_match(event_ts_ms=1_000, candidate_ts_ms=800, tolerance_ms=100)["reason"] == "ASOF_TOLERANCE_EXCEEDED"


def test_bug110_cross_venue_future_observation_is_refused() -> None:
    result = causal_event_admission(event_ts_ms=2_000, receive_ts_ms=2_000, decision_ts_ms=1_000)
    assert result["status"] == "NO_TRADE"
    assert result["reason"] == "EVENT_AFTER_DECISION"


def test_causal_persistence_rejects_invalid_sequences_and_future_payload_without_mutation() -> None:
    persistence = PersistanceCausale()
    assert persistence.ajouter(type_entree=SNAPSHOT, seq=1, payload={"recv_wall_ts_ms": 100})["ok"]
    assert persistence.ajouter(type_entree=DELTA, seq=True)["raison"] == "SEQ_INVALIDE"
    assert persistence.ajouter(type_entree=DELTA, seq=1.5)["raison"] == "SEQ_INVALIDE"
    assert persistence.ajouter(type_entree="OTHER", seq=2)["raison"] == "TYPE_INVALIDE"
    assert persistence.ajouter(type_entree=DELTA, seq=2, payload={"exchange_ts_ms": 101, "recv_wall_ts_ms": 100})["raison"] == "EVENT_AFTER_RECEIVE"
    assert persistence.ordre() == [1]


def test_bug111_frozen_timestamp_cannot_be_corrected_after_training() -> None:
    timestamp = CausalTimestamp(None, 1_000, 2_000, 1_001)
    with pytest.raises(AttributeError):
        timestamp.recv_wall_ts_ms = 2_000  # type: ignore[misc]


def test_bug112_write_timestamp_is_distinct_from_event_receive_timestamp() -> None:
    timestamp = CausalTimestamp(None, 1_000, None, 1_010)
    assert timestamp.recv_wall_ts_ms == 1_000
    assert timestamp.observable_at_ms == 1_010


def test_bug113_monotonic_clock_cannot_cross_collector_restart() -> None:
    left = CausalTimestamp(None, 1_000, 10, 1_000, connection_id="old")
    right = CausalTimestamp(None, 1_001, 1, 1_001, connection_id="new")
    with pytest.raises(ValueError, match="across connections"):
        compare_monotonic_within_connection(left, right)


def test_bug114_fractional_millisecond_resolution_is_not_truncated() -> None:
    parsed = causal_timestamp_from_record({"recv_wall_ts_ms": 1_000.5})
    assert parsed.recv_wall_ts_ms is None


def test_bug115_extreme_receive_delay_is_refused() -> None:
    result = causal_event_admission(event_ts_ms=1_000, receive_ts_ms=2_000, decision_ts_ms=3_000, max_age_ms=500)
    assert result["status"] == "NO_TRADE"
    assert result["reason"] == "RECEIVE_LATENCY_EXCEEDED"


def test_bug116_decision_horizon_remains_anchored_to_decision_clock() -> None:
    result = causal_event_admission(event_ts_ms=1_000, receive_ts_ms=1_100, decision_ts_ms=1_100)
    assert result["status"] == "PROVEN"
    assert result["decision_ts_ms"] == 1_100


def test_bug117_missing_source_timestamp_is_not_replaced_by_now() -> None:
    assert causal_timestamp_from_record({"age_ms": 1}).recv_wall_ts_ms is None


def test_bug118_cutoff_boundary_is_inclusive() -> None:
    result = causal_event_admission(event_ts_ms=1_000, receive_ts_ms=1_000, decision_ts_ms=1_000, feature_cutoff_ts_ms=1_000)
    assert result["status"] == "PROVEN"


def test_bug119_replay_uses_explicit_utc_not_local_dst() -> None:
    assert parse_utc_epoch_ms("2026-11-01T01:30:00+00:00") == 1_793_496_600_000
    assert parse_utc_epoch_ms("2026-11-01T01:30:00") is None


def test_bug120_clock_provenance_survives_record_normalization() -> None:
    parsed = causal_timestamp_from_record({"recv_wall_ts_ms": 1_000, "clock_provenance": "ntp:ok"})
    assert parsed.clock_source == "ntp:ok"
