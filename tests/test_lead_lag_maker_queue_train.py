from __future__ import annotations

from pathlib import Path
import pytest

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


def _signed_trade(*, ts_ms: int, trade_id: str) -> dict:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "received_ts_ms": ts_ms - 2,
        "written_ts_ms": ts_ms,
        "observable_at_ms": ts_ms,
        "exchange_ts_ms": ts_ms - 5,
        "side": "A",
        "px": 100.0,
        "sz": 1.25,
        "trade_id": trade_id,
        "feed_quality_score": 1.0,
        "data_gate_ready": True,
        "quality_reasons": [],
        "source": "hyperliquid:recorded:trades",
        "data_origin": "RECORDED_REAL",
        "read_only": True,
        "real_execution": False,
    }


def test_maker_queue_fill_requiert_flux_agressif_signe_apres_observation() -> None:
    books = [
        _book(1_000, bid=100.0, ask=100.2, bid_size=5.0, ask_size=5.0),
        _book(1_100, bid=100.0, ask=100.2, bid_size=4.0, ask_size=5.0),
        _book(1_200, bid=100.0, ask=100.2, bid_size=2.0, ask_size=5.0),
        _book(1_300, bid=100.0, ask=100.2, bid_size=0.5, ask_size=5.0),
    ]
    aggressive_trades = [
        {"ts_ms": 1_100, "price": 100.0, "qty": 1.0, "aggressor_side": "SELL"},
        {"ts_ms": 1_200, "price": 100.0, "qty": 2.0, "aggressor_side": "SELL"},
        {"ts_ms": 1_300, "price": 100.0, "qty": 2.3, "aggressor_side": "SELL"},
    ]

    decision = module.evaluate_measured_maker_queue_fill(
        books,
        aggressive_trades,
        side="BUY",
        observable_at_ms=1_000,
        deadline_ms=1_300,
        notional_usd=25.0,
    )

    assert decision["status"] == "FILLED_MEASURED_QUEUE"
    assert decision["queue_model"] == "RISK_AVERSE_SIGNED_TRADE_FLOW_FULL_ORDER_V2"
    assert decision["limit_price"] == 100.0
    assert decision["queue_ahead_qty"] == 5.0
    assert decision["aggressive_qty_at_level"] == 5.3
    assert decision["order_qty"] == 0.25
    assert decision["remaining_order_qty"] == 0.0
    assert decision["fill_ts_ms"] == 1_300
    assert decision["paper_read_only"] is True
    assert decision["real_execution"] is False


def test_maker_queue_ne_certifie_pas_un_simple_depassement_de_la_file() -> None:
    books = [
        _book(1_000, bid=100.0, ask=100.2, bid_size=5.0, ask_size=5.0),
    ]
    aggressive_trades = [
        {"ts_ms": 1_100, "price": 100.0, "qty": 5.1, "aggressor_side": "SELL"},
    ]

    decision = module.evaluate_measured_maker_queue_fill(
        books,
        aggressive_trades,
        side="BUY",
        observable_at_ms=1_000,
        deadline_ms=1_100,
        notional_usd=25.0,
    )

    assert decision["status"] == "NOT_FILLED_MEASURED_QUEUE"
    assert decision["filled"] is False
    assert decision["remaining_queue_ahead_qty"] == 0.0
    assert decision["remaining_order_qty"] == pytest.approx(0.15)


def test_maker_queue_refuse_touch_sans_queue_mesurable() -> None:
    books = [
        {"ts_ms": 1_000, "bid": 100.0, "ask": 100.2, "data_origin": "RECORDED_REAL"},
        {"ts_ms": 1_100, "bid": 99.9, "ask": 100.0, "data_origin": "RECORDED_REAL"},
    ]

    decision = module.evaluate_measured_maker_queue_fill(
        books,
        [],
        side="BUY",
        observable_at_ms=1_000,
        deadline_ms=1_100,
        notional_usd=25.0,
    )

    assert decision["status"] == "MAKER_FILL_UNMEASURABLE"
    assert decision["filled"] is False
    assert decision["reason"] == "MISSING_QUEUE_DEPTH"


def test_maker_queue_refuse_depletion_sans_flux_agressif_signe() -> None:
    books = [
        _book(1_000, bid=100.0, ask=100.2, bid_size=5.0, ask_size=5.0),
        _book(1_100, bid=100.0, ask=100.2, bid_size=0.1, ask_size=5.0),
    ]

    decision = module.evaluate_measured_maker_queue_fill(
        books,
        [],
        side="BUY",
        observable_at_ms=1_000,
        deadline_ms=1_100,
        notional_usd=25.0,
    )

    assert decision["status"] == "NOT_FILLED_MEASURED_QUEUE"
    assert decision["queue_ahead_qty"] == 5.0
    assert decision["aggressive_qty_at_level"] == 0.0
    assert decision["remaining_order_qty"] == 0.25


def test_maker_queue_nutilise_jamais_un_trade_avant_observation() -> None:
    books = [
        _book(900, bid=100.0, ask=100.2, bid_size=0.1, ask_size=5.0),
        _book(1_000, bid=100.0, ask=100.2, bid_size=5.0, ask_size=5.0),
        _book(1_100, bid=100.0, ask=100.2, bid_size=4.9, ask_size=5.0),
    ]
    aggressive_trades = [
        {"ts_ms": 900, "price": 100.0, "qty": 10.0, "aggressor_side": "SELL"},
        {"ts_ms": 1_100, "price": 100.0, "qty": 0.1, "aggressor_side": "SELL"},
    ]

    decision = module.evaluate_measured_maker_queue_fill(
        books,
        aggressive_trades,
        side="BUY",
        observable_at_ms=1_000,
        deadline_ms=1_100,
        notional_usd=25.0,
    )

    assert decision["status"] == "NOT_FILLED_MEASURED_QUEUE"
    assert decision["queue_ahead_qty"] == 5.0
    assert decision["aggressive_qty_at_level"] == 0.1


def test_train_public_trade_loader_clamps_source_windows_before_heldout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_ms = 1_800_000_000_000
    train_end_ms = start_ms + 2_000
    event_ms = start_ms + 1_500
    calls: list[tuple[int, int]] = []

    def fake_history(_root, *, start_ms, end_ms, **_kwargs):
        calls.append((int(start_ms), int(end_ms)))
        assert int(end_ms) <= train_end_ms
        return (
            {},
            {
                "ETH": [
                    _signed_trade(ts_ms=event_ms + 100, trade_id="train-1"),
                    _signed_trade(ts_ms=train_end_ms + 1, trade_id="heldout-must-not-pass"),
                ]
            },
            {"source_time_filter_applied": True, "real_execution": False},
        )

    monkeypatch.setattr(module, "load_market_microstructure_history", fake_history)

    trades, meta = module.load_train_public_trade_history(
        tmp_path,
        [event_ms],
        train_ranges=[(start_ms, train_end_ms)],
        before_ms=100,
        after_ms=5_000,
    )

    assert calls == [(event_ms - 100, train_end_ms)]
    assert [row["trade_id"] for row in trades["ETH"]] == ["train-1"]
    assert trades["ETH"][0]["side"] == "A"
    assert meta["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert meta["heldout_loaded"] is False
    assert meta["rows_rejected_outside_train"] == 1
    assert meta["source_windows"] == [[event_ms - 100, train_end_ms]]
    assert meta["paper_read_only"] is True
    assert meta["real_execution"] is False


def test_train_public_trade_loader_fails_closed_on_non_recorded_or_unsigned_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_ms = 1_800_000_000_000
    end_ms = start_ms + 10_000
    valid = _signed_trade(ts_ms=start_ms + 1_000, trade_id="valid")
    duplicate = dict(valid)
    unsigned = {**valid, "trade_id": "unsigned", "side": ""}
    synthetic = {**valid, "trade_id": "synthetic", "data_origin": "SYNTHETIC"}
    real_execution = {**valid, "trade_id": "real", "real_execution": True}

    monkeypatch.setattr(
        module,
        "load_market_microstructure_history",
        lambda *_args, **_kwargs: (
            {},
            {"ETH": [valid, duplicate, unsigned, synthetic, real_execution]},
            {"source_time_filter_applied": True, "real_execution": False},
        ),
    )

    trades, meta = module.load_train_public_trade_history(
        tmp_path,
        [start_ms + 1_000],
        train_ranges=[(start_ms, end_ms)],
    )

    assert [row["trade_id"] for row in trades["ETH"]] == ["valid"]
    assert meta["duplicate_trades_rejected"] == 1
    assert meta["invalid_or_unsafe_trades_rejected"] == 3


def test_train_microstructure_loader_clamps_books_and_trades_to_train(
    tmp_path: Path,
    monkeypatch,
) -> None:
    start_ms = 1_800_000_000_000
    train_end_ms = start_ms + 2_000
    event_ms = start_ms + 1_500

    valid_book = {
        "coin": "ETH",
        "ts_ms": event_ms + 50,
        "bid": 100.0,
        "ask": 100.1,
        "bid_size": 2.0,
        "ask_size": 3.0,
        "source": "hyperliquid:recorded:l2Book",
        "data_origin": "RECORDED_REAL",
        "read_only": True,
        "real_execution": False,
    }
    heldout_book = {**valid_book, "ts_ms": train_end_ms + 1}

    def fake_history(_root, *, start_ms, end_ms, **_kwargs):
        assert int(end_ms) == train_end_ms
        return (
            {"ETH": [valid_book, heldout_book]},
            {
                "ETH": [
                    _signed_trade(ts_ms=event_ms + 100, trade_id="train"),
                    _signed_trade(ts_ms=train_end_ms + 1, trade_id="heldout"),
                ]
            },
            {"source_time_filter_applied": True, "real_execution": False},
        )

    monkeypatch.setattr(module, "load_market_microstructure_history", fake_history)

    books, trades, meta = module.load_train_microstructure_history(
        tmp_path,
        [event_ms],
        train_ranges=[(start_ms, train_end_ms)],
        before_ms=100,
        after_ms=5_000,
    )

    assert [row["ts_ms"] for row in books["ETH"]] == [event_ms + 50]
    assert [row["trade_id"] for row in trades["ETH"]] == ["train"]
    assert meta["heldout_loaded"] is False
    assert meta["book_rows_rejected_outside_train"] == 1
    assert meta["trade_rows_rejected_outside_train"] == 1
