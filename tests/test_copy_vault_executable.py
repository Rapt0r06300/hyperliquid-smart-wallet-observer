from __future__ import annotations

import math

from hl_observer.backtesting.copy_vault_executable import (
    calibrate_train_only,
    cluster_metaorders,
    evaluate_frozen,
    execute_metaorder,
    replay_metaorders,
    summarize,
    temporal_evidence,
)


def _entry(
    event_id: str, ts_ms: int, *, coin: str = "BTC", direction: int = 1, vault: str = "0xA"
) -> dict:
    return {
        "event_id": event_id,
        "ts_ms": ts_ms,
        "coin": coin,
        "direction": direction,
        "vault": vault,
        "taille_usd": 100.0,
        "move_frac": 0.01,
    }


def _book(ts_ms: int, bid: float, ask: float, *, capacity: float = 1_000.0, line: int = 1) -> dict:
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "capacity_usd": capacity,
        "source_line": line,
    }


def test_metaorders_collapse_slices_even_when_other_coin_is_interleaved() -> None:
    entries = [
        _entry("a", 1_000),
        _entry("other", 20_000, coin="ETH"),
        _entry("b", 40_000),
        _entry("b", 40_000),
        _entry("c", 120_001),
    ]

    metaorders, audit = cluster_metaorders(entries, gap_ms=60_000)

    btc = [row for row in metaorders if row["coin"] == "BTC"]
    assert [row["fill_count"] for row in btc] == [2, 1]
    assert audit["duplicate_events_rejected"] == 1
    assert audit["sliced_fills_collapsed"] == 1


def test_stale_reference_is_refused_instead_of_using_future_price() -> None:
    metaorder = cluster_metaorders([_entry("a", 1_000)])[0][0]
    books = [_book(40_001, 99.0, 101.0)]

    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert trade is None
    assert reason == "STALE_OR_MISSING_REFERENCE_BOOK"


def test_long_and_short_use_marketable_prices_and_reconcile_costs() -> None:
    books = [
        _book(1_000, 99.0, 101.0, line=1),
        _book(61_000, 100.0, 102.0, line=2),
        _book(361_000, 109.0, 111.0, line=3),
    ]
    long_meta = cluster_metaorders([_entry("long", 1_000)])[0][0]
    short_meta = cluster_metaorders([_entry("short", 1_000, direction=-1)])[0][0]

    long_trade, long_reason = execute_metaorder(long_meta, books, horizon_ms=300_000)
    short_trade, short_reason = execute_metaorder(short_meta, books, horizon_ms=300_000)

    assert long_reason == short_reason == "LIQUIDATABLE_NET"
    assert long_trade is not None and short_trade is not None
    assert long_trade["entry_price"] == 102.0 and long_trade["exit_price"] == 109.0
    assert short_trade["entry_price"] == 100.0 and short_trade["exit_price"] == 111.0
    for trade in (long_trade, short_trade):
        expected = (
            trade["gross_pnl_usd"]
            - trade["fees_usd"]
            - trade["spread_cost_usd"]
            - trade["slippage_cost_usd"]
            - trade["latency_cost_usd"]
        )
        assert math.isclose(expected, trade["net_pnl_usd"], abs_tol=1e-8)
        assert trade["liquidatable_net"] is True
        assert trade["paper_read_only"] is True and trade["real_execution"] is False


def test_capacity_and_duplicate_trade_guards_fail_closed() -> None:
    metaorder = cluster_metaorders([_entry("a", 1_000)])[0][0]
    books = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0, capacity=149.99),
        _book(361_000, 109.0, 111.0),
    ]
    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)
    assert trade is None and reason == "OBSERVED_TOP_CAPACITY_TOO_LOW"

    dense = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0),
        _book(361_000, 109.0, 111.0),
    ]
    trades, diagnostics = replay_metaorders(
        [metaorder, dict(metaorder)], {"BTC": dense}, horizon_ms=300_000
    )
    assert len(trades) == 1
    assert diagnostics["DUPLICATE_TRADE_ID_REJECTED"] == 1
    assert summarize(trades)["duplicate_trade_ids"] == 0


def test_all_win_profit_factor_is_unmeasured_not_json_infinity() -> None:
    metaorder = cluster_metaorders([_entry("winner", 1_000)])[0][0]
    books = [
        _book(1_000, 99.0, 101.0),
        _book(61_000, 100.0, 102.0),
        _book(361_000, 109.0, 111.0),
    ]
    trade, reason = execute_metaorder(metaorder, books, horizon_ms=300_000)

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None and trade["net_pnl_usd"] > 0
    summary = summarize([trade])
    assert summary["profit_factor"] is None
    assert "Infinity" not in __import__("json").dumps(summary)


def test_walk_forward_selects_on_train_and_forward_is_strictly_post_freeze() -> None:
    entries = []
    books = []
    spacing = 4_000_000
    for index in range(16):
        signal = 1_000 + index * spacing
        entries.append(_entry(f"e-{index}", signal))
        books.extend([
            _book(signal, 99.0, 101.0, line=index * 3 + 1),
            _book(signal + 60_000, 100.0, 102.0, line=index * 3 + 2),
            _book(signal + 360_000, 109.0, 111.0, line=index * 3 + 3),
        ])
    metaorders = cluster_metaorders(entries)[0]
    calibration = calibrate_train_only(metaorders, {"BTC": books})
    assert calibration["selection_scope"] == "TRAIN_ONLY"
    assert calibration["selection_eligible"] is True

    freeze_at = int(metaorders[12]["signal_ts_ms"]) - 1
    parameters = {
        "selected_horizon_ms": calibration["selected_horizon_ms"],
        "walk_forward_bounds": calibration["bounds"],
    }
    evaluation = evaluate_frozen(
        metaorders, {"BTC": books}, frozen_parameters=parameters, frozen_at_ms=freeze_at
    )
    temporal = temporal_evidence(evaluation)

    assert temporal["oos"]["no_lookahead"] is True
    assert temporal["forward"]["post_freeze"] is True
    assert all(
        trade["signal_ts_ms"] > freeze_at
        for trade in evaluation["trades"]["forward"]
    )
    assert temporal["placebos"]["beaten"] is True
