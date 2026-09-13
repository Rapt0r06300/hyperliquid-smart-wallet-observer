from __future__ import annotations

import pytest

from hl_observer.backtesting import lead_lag_queue_replay as replay


def _book(ts_ms: int, *, bid: float, ask: float) -> dict[str, object]:
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


def _scenario(*, baseline_bid: float, baseline_ask: float):
    tape = {
        "ETH": {
            "TRADE": [
                (1_000_000_000, 100.0, 1),
                (2_000_000_000, 100.25, 1),
            ]
        }
    }
    books = {
        "ETH": [
            _book(1_000, bid=baseline_bid, ask=baseline_ask),
            _book(2_100, bid=2_000.0, ask=2_001.0),
            _book(3_100, bid=2_100.0, ask=2_101.0),
            _book(7_300, bid=2_010.0, ask=2_011.0),
        ]
    }
    public_trades = {
        "ETH": [
            _trade(2_140, side="A", price=2_000.0, size=1.1),
        ]
    }
    return tape, books, public_trades


def test_already_priced_veto_rejects_before_fifo_when_source_move_is_absorbed() -> None:
    tape, books, trades = _scenario(baseline_bid=1_995.5, baseline_ask=1_996.5)

    report = replay.replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
        already_priced_max_fraction=0.5,
    )

    assert report["maker_queue_candidates"] == []
    assert report["diagnostics"]["ALREADY_PRICED"] == 1
    assert report["parameters"]["already_priced_max_fraction"] == pytest.approx(0.5)


def test_already_priced_veto_does_not_consult_post_entry_books() -> None:
    tape, books, trades = _scenario(baseline_bid=2_000.0, baseline_ask=2_001.0)
    books["ETH"].insert(2, _book(2_200, bid=2_500.0, ask=2_501.0))

    report = replay.replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
        already_priced_max_fraction=0.5,
    )

    assert report["diagnostics"].get("ALREADY_PRICED", 0) == 0
    assert len(report["maker_queue_candidates"]) == 1
    assert report["maker_queue_candidates"][0]["entry_book_ts_ms"] == 2_100


def test_already_priced_veto_is_opt_in_and_legacy_default_is_unchanged() -> None:
    tape, books, trades = _scenario(baseline_bid=1_995.5, baseline_ask=1_996.5)

    report = replay.replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    assert report["parameters"]["already_priced_max_fraction"] is None
    assert len(report["maker_queue_candidates"]) == 1


def test_already_priced_veto_rejects_non_positive_thresholds() -> None:
    with pytest.raises(ValueError, match="INVALID_ALREADY_PRICED_MAX_FRACTION"):
        replay.replay_lead_lag_queue_maker(
            {},
            {},
            {},
            latency_evidence={"measured": True, "p95_ms": 100.0},
            already_priced_max_fraction=0.0,
        )
