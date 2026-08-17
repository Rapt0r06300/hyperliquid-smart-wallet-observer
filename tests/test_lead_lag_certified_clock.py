from __future__ import annotations

from hl_observer.backtesting.lead_lag_certified_clock import (
    CERTIFIED_TIMESTAMP_POLICY,
    certified_event_time_ns,
    certified_protocol_signature,
)


def test_monotonic_only_timestamp_is_not_certifiable() -> None:
    assert certified_event_time_ns({"recu_ns": 123456789}) is None


def test_wall_clock_is_certifiable_and_converted_to_ns() -> None:
    assert certified_event_time_ns({"ts_wall_ms": 1234.5, "recu_ns": 1}) == 1_234_500_000
    assert certified_event_time_ns({"recv_wall_ts_ms": 2}) == 2_000_000


def test_protocol_signature_ne_promet_plus_le_fallback_monotone() -> None:
    signature = certified_protocol_signature()
    assert signature["timestamp_clock"] == CERTIFIED_TIMESTAMP_POLICY
    assert signature["monotonic_only_rows_eligible_for_economic_proof"] is False
    assert "recu_ns_fallback" not in signature["timestamp_clock"]
