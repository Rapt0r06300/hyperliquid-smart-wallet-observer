from __future__ import annotations

import math

import pytest

from hl_observer.backtesting.lead_lag_queue_replay import replay_lead_lag_queue_maker


def _book(ts_ms: int, *, mid: float) -> dict[str, object]:
    bid = mid - 0.5
    ask = mid + 0.5
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "exchange_ts_ms": ts_ms - 5,
        "bid": bid,
        "ask": ask,
        "bid_size": 1.0,
        "ask_size": 1.0,
        "bid_top_usd": bid * 10.0,
        "ask_top_usd": ask * 10.0,
        "data_gate_ready": True,
        "real_execution": False,
    }


def _trade(ts_ms: int, *, side: str, price: float, size: float) -> dict[str, object]:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "exchange_ts_ms": ts_ms - 5,
        "side": side,
        "px": price,
        "sz": size,
        "data_gate_ready": True,
        "real_execution": False,
    }


def _scenario(*, entry_mid: float, future_mid: float | None = None):
    # 25 bps Binance shock from 1_000 -> 2_000 ms.
    tape = {"ETH": {"TRADE": [(1_000_000_000, 100.0, 1), (2_000_000_000, 100.25, 1)]}}
    baseline_mid = 2_000.0
    entry_ms = 2_100
    entry_bid = entry_mid - 0.5
    books = [
        _book(1_000, mid=baseline_mid),
        _book(entry_ms, mid=entry_mid),
    ]
    if future_mid is not None:
        books.append(_book(entry_ms + 500, mid=future_mid))
    books.append(_book(7_300, mid=entry_mid + 10.0))
    own_qty = 25.0 / entry_bid
    trades = [
        _trade(entry_ms + 100, side="A", price=entry_bid, size=1.0),
        _trade(entry_ms + 200, side="A", price=entry_bid, size=own_qty),
    ]
    return tape, {"ETH": books}, {"ETH": trades}


def test_already_priced_veto_rejects_before_fifo_entry() -> None:
    # 20 bps of HL movement / 25 bps source shock = 80% already absorbed.
    tape, books, trades = _scenario(entry_mid=2_004.0)

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
        already_priced_max_fraction=0.75,
    )

    assert report["maker_queue_candidates"] == []
    assert report["diagnostics"]["ALREADY_PRICED"] == 1
    assert report["parameters"]["already_priced_max_fraction"] == pytest.approx(0.75)


def test_already_priced_veto_never_looks_past_entry_decision() -> None:
    tape, books, trades = _scenario(entry_mid=2_000.0, future_mid=2_010.0)

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
        already_priced_max_fraction=0.75,
    )

    assert len(report["maker_queue_candidates"]) == 1
    assert report["diagnostics"].get("ALREADY_PRICED", 0) == 0


def test_already_priced_none_preserves_legacy_behavior() -> None:
    tape, books, trades = _scenario(entry_mid=2_004.0)

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
        already_priced_max_fraction=None,
    )

    assert len(report["maker_queue_candidates"]) == 1
    assert report["parameters"]["already_priced_max_fraction"] is None


@pytest.mark.parametrize("value", [0.0, -0.1, math.nan, math.inf])
def test_already_priced_threshold_must_be_positive_and_finite(value: float) -> None:
    tape, books, trades = _scenario(entry_mid=2_000.0)

    with pytest.raises(ValueError, match="INVALID_ALREADY_PRICED_MAX_FRACTION"):
        replay_lead_lag_queue_maker(
            tape,
            books,
            trades,
            latency_evidence={"measured": True, "p95_ms": 100.0},
            already_priced_max_fraction=value,
        )
