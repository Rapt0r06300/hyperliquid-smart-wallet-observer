from __future__ import annotations

import math
import json

from hl_observer.backtesting.copy_vault_executable import (
    COPY_DELAY_MS,
    HORIZONS_MS,
    MAX_TARGET_LAG_MS,
    calibrate_train_only,
    cluster_metaorders,
    evaluate_frozen,
    execute_metaorder,
    load_observed_books,
    replay_metaorders,
    select_causal_protocol_inputs,
    summarize,
    temporal_bounds,
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


def _book(
    ts_ms: int,
    bid: float,
    ask: float,
    *,
    capacity: float = 1_000.0,
    line: int = 1,
    causal: bool = False,
) -> dict:
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "capacity_usd": capacity,
        "source_line": line,
        "causal_observation": causal,
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


def test_metaorder_live_emploie_reception_locale_et_backfill_ne_prouve_pas_forward() -> None:
    live = {
        **_entry("live", 1_000),
        "source": "LIVE_WS",
        "is_snapshot": False,
        "observed_at_ms": 1_025,
    }
    history = _entry("history", 2_000)
    metaorders, audit = cluster_metaorders([live, history], gap_ms=1)

    by_id = {row["member_event_ids"][0]: row for row in metaorders}
    assert by_id["live"]["signal_ts_ms"] == 1_025
    assert by_id["live"]["causal_forward_eligible"] is True
    assert by_id["history"]["causal_forward_eligible"] is False
    assert audit["causal_forward_metaorders"] == 1

    books = {
        "BTC": [
            _book(1_025, 99.0, 101.0, line=1, causal=True),
            _book(61_025, 100.0, 102.0, line=2, causal=True),
            _book(361_025, 109.0, 111.0, line=3, causal=True),
            _book(2_000, 99.0, 101.0, line=4),
            _book(62_000, 100.0, 102.0, line=5),
            _book(362_000, 109.0, 111.0, line=6),
        ]
    }
    books["BTC"].sort(key=lambda row: row["ts_ms"])
    trades, diagnostics = replay_metaorders(
        metaorders,
        books,
        horizon_ms=300_000,
        require_causal_observation=True,
    )

    assert len(trades) == 1 and trades[0]["signal_source"] == "LIVE_WS"
    assert diagnostics["NON_CAUSAL_FORWARD_SIGNAL"] == 1


def test_forward_refuse_un_carnet_non_causal() -> None:
    entry = {
        **_entry("live", 1_000),
        "source": "LIVE_WS",
        "is_snapshot": False,
        "observed_at_ms": 1_025,
    }
    metaorder = cluster_metaorders([entry])[0][0]
    books = [
        _book(1_025, 99.0, 101.0),
        _book(61_025, 100.0, 102.0),
        _book(361_025, 109.0, 111.0),
    ]

    trades, diagnostics = replay_metaorders(
        [metaorder], {"BTC": books}, horizon_ms=300_000,
        require_causal_observation=True,
    )

    assert trades == []
    assert diagnostics["NON_CAUSAL_FORWARD_BOOK"] == 1


def test_loader_separe_historique_et_tape_ws_causale(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "carnet_venues.jsonl").write_text(json.dumps({
        "coin": "BTC", "collecte_ts": 1.0, "hl_bid": 99.0,
        "hl_ask": 101.0, "taille_min_usd": 500.0,
    }) + "\n", encoding="utf-8")
    causal = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC", "received_at_ms": 2_010, "exchange_ts_ms": 2_000,
        "bid": 100.0, "ask": 102.0, "capacity_usd": 700.0,
        "source": "HYPERLIQUID_L2_WS", "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(causal) + "\n", encoding="utf-8"
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert [row["causal_observation"] for row in books["BTC"]] == [False, True]
    assert books["BTC"][1]["ts_ms"] == 2_010
    assert audit["source_counts"] == {"historical_observed": 1, "causal_ws": 1}


def test_protocol_inputs_excluent_backfill_et_carnet_non_causal() -> None:
    historical = cluster_metaorders([_entry("history", 1_000)])[0][0]
    live = cluster_metaorders([{
        **_entry("live", 2_000),
        "source": "LIVE_WS",
        "is_snapshot": False,
        "observed_at_ms": 2_025,
    }])[0][0]
    books = {
        "BTC": [
            _book(1_000, 99.0, 101.0),
            _book(2_025, 100.0, 102.0, causal=True),
        ],
        "ETH": [_book(3_000, 10.0, 11.0, causal=True)],
    }

    metaorders, causal_books, audit = select_causal_protocol_inputs(
        [historical, live], books
    )

    assert [row["metaorder_id"] for row in metaorders] == [live["metaorder_id"]]
    assert list(causal_books) == ["BTC"]
    assert len(causal_books["BTC"]) == 1
    assert audit["causal_protocol_metaorders"] == 1
    assert audit["historical_or_noncausal_metaorders_excluded"] == 1
    assert audit["causal_protocol_book_rows"] == 1
    assert audit["historical_or_noncausal_book_rows_excluded"] == 2


def test_calibration_causale_refuse_un_signal_historique() -> None:
    historical = cluster_metaorders([
        _entry(f"history-{index}", 1_000 + index * 4_000_000)
        for index in range(12)
    ])[0]
    books = {
        "BTC": [
            _book(1_000, 99.0, 101.0, causal=True),
            _book(61_000, 100.0, 102.0, causal=True),
            _book(361_000, 109.0, 111.0, causal=True),
        ]
    }

    result = calibrate_train_only(
        historical,
        books,
        require_causal_observation=True,
    )

    assert result["selection_eligible"] is False
    assert result["causal_observation_required"] is True
    assert all(
        row["diagnostics"].get("NON_CAUSAL_FORWARD_SIGNAL", 0) > 0
        for row in result["grid"]
    )


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
    for index in range(20):
        signal = 1_000 + index * spacing
        entries.append({
            **_entry(f"e-{index}", signal),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": signal,
        })
        books.extend([
            _book(signal, 99.0, 101.0, line=index * 3 + 1, causal=True),
            _book(signal + 60_000, 100.0, 102.0, line=index * 3 + 2, causal=True),
            _book(signal + 360_000, 109.0, 111.0, line=index * 3 + 3, causal=True),
        ])
    metaorders = cluster_metaorders(entries)[0]
    # Freeze the protocol on the first 16 observations, then expose four
    # genuinely later causal observations as the forward segment.
    calibration = calibrate_train_only(metaorders[:16], {"BTC": books})
    assert calibration["selection_scope"] == "TRAIN_ONLY"
    assert calibration["selection_eligible"] is True

    freeze_at = int(metaorders[15]["signal_ts_ms"])
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


def test_calibration_uses_candidate_horizon_specific_purge() -> None:
    entries = [
        {
            **_entry(f"e-{index}", 1_000 + index * 4_000_000),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": 1_000 + index * 4_000_000,
        }
        for index in range(16)
    ]
    metaorders = cluster_metaorders(entries)[0]

    calibration = calibrate_train_only(metaorders, {"BTC": []})

    for row in calibration["grid"]:
        expected = COPY_DELAY_MS + int(row["horizon_ms"]) + MAX_TARGET_LAG_MS
        assert row["bounds"]["purge_ms"] == expected
    assert len({row["bounds"]["purge_ms"] for row in calibration["grid"]}) == len(HORIZONS_MS)


def test_selected_bounds_match_selected_horizon_and_default_is_shortest() -> None:
    entries = [
        {
            **_entry(f"e-{index}", 1_000 + index * 4_000_000),
            "source": "LIVE_WS",
            "is_snapshot": False,
            "observed_at_ms": 1_000 + index * 4_000_000,
        }
        for index in range(16)
    ]
    metaorders = cluster_metaorders(entries)[0]

    result = calibrate_train_only(metaorders, {"BTC": []})

    assert result["selection_eligible"] is False
    assert result["selected_horizon_ms"] == HORIZONS_MS[0]
    assert result["bounds"] == result["grid"][0]["bounds"]
    assert result["bounds"] == temporal_bounds(
        metaorders,
        purge_ms=COPY_DELAY_MS + HORIZONS_MS[0] + MAX_TARGET_LAG_MS,
    )
