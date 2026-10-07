from __future__ import annotations

from hl_observer.backtesting.lead_lag_microstructure_confirmation import (
    ECONOMIC_TARGET_USD_DAY,
    HORIZONS_MS,
    NOTIONALS_USD,
    SHOCK_THRESHOLDS_BPS,
    SHOCK_WINDOWS_MS,
    confirm_shocks_with_book_and_flow,
    trial_count,
)


def _book(ts: int, bid_size: float, ask_size: float, source: str = "same") -> dict:
    return {
        "observable_at_ms": ts,
        "ts_ms": ts,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "source_id": source,
    }


def _trade(ts: int, direction: float, qty: float, source: str = "same") -> dict:
    return {
        "observable_at_ms": ts,
        "price": 100.0,
        "qty": qty,
        "direction": direction,
        "source_id": source,
    }


def test_microstructure_economic_grid_is_predeclared_and_counted() -> None:
    assert NOTIONALS_USD == (25.0, 75.0, 150.0, 300.0)
    assert ECONOMIC_TARGET_USD_DAY == 5.0
    assert trial_count(2) == (
        2
        * len(SHOCK_WINDOWS_MS)
        * len(SHOCK_THRESHOLDS_BPS)
        * len(HORIZONS_MS)
        * len(NOTIONALS_USD)
    )


def test_book_and_flow_confirmation_accepts_only_causal_agreement() -> None:
    shock_ms = 2_000
    shocks = [(shock_ms * 1_000_000, 1.0)]
    books = [_book(1_950, 9.0, 1.0)]
    trades = [
        _trade(1_200, 1.0, 1.0),
        _trade(1_600, 1.0, 2.0),
        _trade(2_000, 1.0, 3.0),
    ]
    accepted, audit = confirm_shocks_with_book_and_flow(
        shocks, books, trades
    )
    assert accepted == shocks
    assert audit["accepted"] == 1
    assert audit["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"


def test_book_and_flow_confirmation_rejects_adverse_flow() -> None:
    shock_ms = 2_000
    shocks = [(shock_ms * 1_000_000, 1.0)]
    books = [_book(1_950, 9.0, 1.0)]
    trades = [
        _trade(1_200, -1.0, 4.0),
        _trade(1_600, -1.0, 4.0),
        _trade(2_000, 1.0, 1.0),
    ]
    accepted, audit = confirm_shocks_with_book_and_flow(
        shocks, books, trades
    )
    assert accepted == []
    assert audit["flow_conflict"] == 1


def test_book_and_flow_confirmation_rejects_future_or_stale_book() -> None:
    shock_ms = 2_000
    shocks = [(shock_ms * 1_000_000, 1.0)]
    trades = [
        _trade(1_500, 1.0, 1.0),
        _trade(1_700, 1.0, 1.0),
        _trade(2_000, 1.0, 1.0),
    ]
    accepted, audit = confirm_shocks_with_book_and_flow(
        shocks,
        [_book(1_000, 9.0, 1.0), _book(2_010, 9.0, 1.0)],
        trades,
    )
    assert accepted == []
    assert audit["stale_book"] == 1


def test_book_and_flow_confirmation_requires_same_source() -> None:
    shock_ms = 2_000
    shocks = [(shock_ms * 1_000_000, 1.0)]
    trades = [
        _trade(1_500, 1.0, 1.0, "lead"),
        _trade(1_700, 1.0, 1.0, "lead"),
        _trade(2_000, 1.0, 1.0, "lead"),
    ]
    accepted, audit = confirm_shocks_with_book_and_flow(
        shocks,
        [_book(1_950, 9.0, 1.0, "different")],
        trades,
    )
    assert accepted == []
    assert audit["missing_same_source_book"] == 1
