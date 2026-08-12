from __future__ import annotations

from hl_observer.simulation.copy_cost_adapter import (
    COPY_ROUNDTRIP_TAKER_FEES_BPS,
    measure_copy_cost_components,
)


def _event(ts_ms: int = 1_700_000_000_000) -> dict:
    return {
        "ts_ms": ts_ms,
        "coin": "BTC",
        "vault": "vault-a",
        "direction": 1,
        "move_frac": 0.10,
    }


def _depth(ts_ms: int, *, capacity: float = 500.0, half_spread: float = 1.25) -> dict:
    return {
        "_ts_ms": ts_ms,
        "_capacity_usd": capacity,
        "hl_demi_spread_bps": half_spread,
    }


def test_complete_copy_cost_evidence_is_causal_and_reconciled() -> None:
    event = _event()
    delay_ms = 60_000
    horizon_ms = 300_000
    entry = event["ts_ms"] + delay_ms
    exit_ = entry + horizon_ms
    snapshots = {
        "BTC": [
            _depth(entry - 500, half_spread=1.0),
            _depth(exit_ - 750, half_spread=1.5),
        ]
    }

    result = measure_copy_cost_components(
        [event],
        snapshots,
        notional_usd=150.0,
        copy_delay_ms=delay_ms,
        horizon_ms=horizon_ms,
        threshold=0.05,
        freshness_ms=3_000.0,
    )

    assert result["complete"] is True
    assert result["selected_events"] == result["matched_events"] == 1
    assert result["failure_counts"] == {}
    assert result["components_bps"] == {
        "fees_bps": COPY_ROUNDTRIP_TAKER_FEES_BPS,
        "spread_bps": 2.5,
        "slippage_bps": 0.0,
        "latency_bps": 0.0,
    }
    assert result["slippage_rule"] == "ZERO_ONLY_WHEN_TOP_CAPACITY_COVERS_NOTIONAL"
    assert result["latency_rule"] == "EMBEDDED_IN_DELAYED_ENTRY_GROSS"
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_future_depth_is_never_used_as_entry_evidence() -> None:
    event = _event()
    delay_ms = 60_000
    horizon_ms = 300_000
    entry = event["ts_ms"] + delay_ms
    exit_ = entry + horizon_ms
    snapshots = {
        "BTC": [
            _depth(entry + 1),
            _depth(exit_ - 10),
        ]
    }

    result = measure_copy_cost_components(
        [event],
        snapshots,
        notional_usd=150.0,
        copy_delay_ms=delay_ms,
        horizon_ms=horizon_ms,
        threshold=0.05,
        freshness_ms=3_000.0,
    )

    assert result["complete"] is False
    assert result["components_bps"] is None
    assert result["matched_events"] == 0
    assert result["failure_counts"]["ENTRY_DEPTH_STALE_OR_FUTURE_ONLY"] == 1


def test_stale_or_undersized_depth_never_becomes_zero_slippage() -> None:
    event = _event()
    delay_ms = 60_000
    horizon_ms = 300_000
    entry = event["ts_ms"] + delay_ms
    exit_ = entry + horizon_ms

    stale = measure_copy_cost_components(
        [event],
        {
            "BTC": [
                _depth(entry - 3_001),
                _depth(exit_ - 100),
            ]
        },
        notional_usd=150.0,
        copy_delay_ms=delay_ms,
        horizon_ms=horizon_ms,
        threshold=0.05,
        freshness_ms=3_000.0,
    )
    assert stale["complete"] is False
    assert stale["components_bps"] is None
    assert stale["failure_counts"]["ENTRY_DEPTH_STALE_OR_FUTURE_ONLY"] == 1

    undersized = measure_copy_cost_components(
        [event],
        {
            "BTC": [
                _depth(entry - 100, capacity=149.99),
                _depth(exit_ - 100, capacity=500.0),
            ]
        },
        notional_usd=150.0,
        copy_delay_ms=delay_ms,
        horizon_ms=horizon_ms,
        threshold=0.05,
        freshness_ms=3_000.0,
    )
    assert undersized["complete"] is False
    assert undersized["components_bps"] is None
    assert undersized["failure_counts"]["ENTRY_TOP_CAPACITY_INSUFFICIENT"] == 1


def test_every_selected_replayed_event_requires_depth_evidence() -> None:
    first = _event()
    second = _event(first["ts_ms"] + 1_000_000)
    second["vault"] = "vault-b"
    delay_ms = 60_000
    horizon_ms = 300_000
    first_entry = first["ts_ms"] + delay_ms
    first_exit = first_entry + horizon_ms

    result = measure_copy_cost_components(
        [first, second],
        {
            "BTC": [
                _depth(first_entry - 100),
                _depth(first_exit - 100),
            ]
        },
        notional_usd=150.0,
        copy_delay_ms=delay_ms,
        horizon_ms=horizon_ms,
        threshold=0.05,
        freshness_ms=3_000.0,
    )

    assert result["selected_events"] == 2
    assert result["matched_events"] == 1
    assert result["complete"] is False
    assert result["components_bps"] is None
    assert result["failure_counts"]["ENTRY_DEPTH_STALE_OR_FUTURE_ONLY"] == 1
