from __future__ import annotations

from hl_observer.backtesting import lead_lag_maker_queue_train as module


def _book(ts_ms: int, *, bid: float, ask: float, bid_size: float, ask_size: float) -> dict:
    return {
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "bid_top_usd": bid * bid_size,
        "ask_top_usd": ask * ask_size,
        "data_origin": "RECORDED_REAL",
        "read_only": True,
        "real_execution": False,
    }


def test_maker_queue_fill_requiert_depletion_mesurable_apres_observation() -> None:
    books = [
        _book(1_000, bid=100.0, ask=100.2, bid_size=5.0, ask_size=5.0),
        _book(1_100, bid=100.0, ask=100.2, bid_size=4.0, ask_size=5.0),
        _book(1_200, bid=100.0, ask=100.2, bid_size=2.0, ask_size=5.0),
        _book(1_300, bid=100.0, ask=100.2, bid_size=0.5, ask_size=5.0),
    ]

    decision = module.evaluate_measured_maker_queue_fill(
        books,
        side="BUY",
        observable_at_ms=1_000,
        deadline_ms=1_300,
        notional_usd=250.0,
    )

    assert decision["status"] == "FILLED_MEASURED_QUEUE"
    assert decision["queue_model"] == "RISK_AVERSE_OBSERVED_DEPLETION"
    assert decision["limit_price"] == 100.0
    assert decision["queue_ahead_usd"] == 500.0
    assert decision["observed_depletion_usd"] == 450.0
    assert decision["fill_ts_ms"] == 1_300
    assert decision["paper_read_only"] is True
    assert decision["real_execution"] is False


def test_maker_queue_refuse_touch_sans_queue_mesurable() -> None:
    books = [
        {"ts_ms": 1_000, "bid": 100.0, "ask": 100.2, "data_origin": "RECORDED_REAL"},
        {"ts_ms": 1_100, "bid": 99.9, "ask": 100.0, "data_origin": "RECORDED_REAL"},
    ]

    decision = module.evaluate_measured_maker_queue_fill(
        books,
        side="BUY",
        observable_at_ms=1_000,
        deadline_ms=1_100,
        notional_usd=25.0,
    )

    assert decision["status"] == "MAKER_FILL_UNMEASURABLE"
    assert decision["filled"] is False
    assert decision["reason"] == "MISSING_QUEUE_DEPTH"


def test_maker_queue_nutilise_jamais_un_snapshot_avant_observation() -> None:
    books = [
        _book(900, bid=100.0, ask=100.2, bid_size=0.1, ask_size=5.0),
        _book(1_000, bid=100.0, ask=100.2, bid_size=5.0, ask_size=5.0),
        _book(1_100, bid=100.0, ask=100.2, bid_size=4.9, ask_size=5.0),
    ]

    decision = module.evaluate_measured_maker_queue_fill(
        books,
        side="BUY",
        observable_at_ms=1_000,
        deadline_ms=1_100,
        notional_usd=25.0,
    )

    assert decision["status"] == "NOT_FILLED_MEASURED_QUEUE"
    assert decision["queue_ahead_usd"] == 500.0
    assert decision["observed_depletion_usd"] == 10.0
