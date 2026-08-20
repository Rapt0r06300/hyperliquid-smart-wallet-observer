from __future__ import annotations

import pytest

from hl_observer.backtesting.lead_lag_queue_replay import (
    detect_rolling_shocks,
    replay_lead_lag_queue_maker,
)


def _book(
    ts_ms: int,
    *,
    bid: float,
    ask: float,
    ready: bool = True,
) -> dict[str, object]:
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
        "data_gate_ready": ready,
        "real_execution": False,
    }


def _trade(
    ts_ms: int,
    *,
    side: str,
    price: float,
    size: float,
    ready: bool = True,
) -> dict[str, object]:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "exchange_ts_ms": ts_ms - 5,
        "side": side,
        "px": price,
        "sz": size,
        "data_gate_ready": ready,
        "real_execution": False,
    }


def _positive_scenario(*, count: int = 1, ready: bool = True):
    lead_trades: list[tuple[int, float, int]] = []
    books: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    for index in range(count):
        base_ms = 10_000 * index + 1_000
        trigger_ms = base_ms + 1_000
        lead_trades.extend(
            [
                (base_ms * 1_000_000, 100.0, 1),
                (trigger_ms * 1_000_000, 100.25, 1),
            ]
        )
        entry_ms = trigger_ms + 100
        books.extend(
            [
                _book(entry_ms, bid=2_000.0, ask=2_001.0, ready=ready),
                # This book is before fill + hold and must never be used to exit.
                _book(entry_ms + 1_000, bid=2_100.0, ask=2_101.0, ready=ready),
                _book(entry_ms + 5_200, bid=2_010.0, ask=2_011.0, ready=ready),
            ]
        )
        trades.extend(
            [
                _trade(entry_ms + 20, side="B", price=2_000.0, size=5.0, ready=ready),
                _trade(entry_ms + 30, side="A", price=2_001.0, size=5.0, ready=ready),
                _trade(entry_ms + 40, side="A", price=2_000.0, size=1.0, ready=ready),
                _trade(entry_ms + 200, side="A", price=2_000.0, size=0.0125, ready=ready),
            ]
        )
    return (
        {"ETH": {"TRADE": lead_trades}},
        {"ETH": books},
        {"ETH": trades},
    )


def test_detect_rolling_shocks_is_causal_and_predeclared() -> None:
    shocks = detect_rolling_shocks(
        [
            (1_000_000_000, 100.0, 1),
            (1_500_000_000, 100.10, 1),
            (2_000_000_000, 100.25, 1),
        ]
    )

    assert len(shocks) == 1
    assert shocks[0]["trigger_ts_ms"] == 2_000
    assert shocks[0]["direction"] == 1
    assert shocks[0]["lead_shock_bps"] == pytest.approx(25.0)


def test_queue_replay_requires_ahead_plus_complete_own_order() -> None:
    tape, books, trades = _positive_scenario()
    trades["ETH"] = trades["ETH"][:-1]

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    assert report["maker_queue_candidates"] == []
    assert report["diagnostics"]["QUEUE_NOT_FULLY_CONSUMED"] == 1


def test_queue_replay_uses_only_correct_aggressor_side_and_exact_price() -> None:
    tape, books, trades = _positive_scenario()

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    row = report["maker_queue_candidates"][0]
    assert row["initial_qty_ahead"] == pytest.approx(1.0)
    assert row["paper_order_qty"] == pytest.approx(0.0125)
    assert row["queue_traded_qty"] == pytest.approx(1.0125)
    assert len(row["queue_events"]) == 2
    assert row["full_fill"] is True


def test_queue_replay_accounts_exact_fees_and_causal_exit() -> None:
    tape, books, trades = _positive_scenario()

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    row = report["maker_queue_candidates"][0]
    assert row["entry_price"] == pytest.approx(2_000.0)
    assert row["exit_price"] == pytest.approx(2_010.0)
    assert row["exit_ts_ms"] == 7_300
    assert row["fees_usd"] == pytest.approx(0.01505625)
    assert row["net_pnl_usd"] == pytest.approx(0.10994375)
    assert row["economic_reconciliation_ok"] is True
    assert row["LIQUIDATABLE_NET"] is True


@pytest.mark.parametrize(
    ("latency_evidence", "ready"),
    [
        ({"measured": False, "p95_ms": 100.0}, True),
        ({"measured": True, "p95_ms": 100.0}, False),
    ],
)
def test_queue_replay_fails_closed_without_latency_or_quality(
    latency_evidence: dict[str, object], ready: bool
) -> None:
    tape, books, trades = _positive_scenario(ready=ready)

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence=latency_evidence,
    )

    row = report["maker_queue_candidates"][0]
    assert row["closed_position"] is True
    assert row["LIQUIDATABLE_NET"] is False


def test_segments_are_frozen_on_shocks_before_fill_outcome() -> None:
    tape, books, trades = _positive_scenario(count=5)

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    rows = report["maker_queue_candidates"]
    assert [row["walk_forward_segment"] for row in rows] == [
        "train",
        "train",
        "train",
        "validation",
        "oos",
    ]
    assert report["segment_summaries"]["train"]["sample_count"] == 3
    assert report["segment_summaries"]["validation"]["sample_count"] == 1
    assert report["segment_summaries"]["oos"]["sample_count"] == 1
    assert report["forward_status"] == "NOT_STARTED_POST_FREEZE"
    assert report["real_execution"] is False
