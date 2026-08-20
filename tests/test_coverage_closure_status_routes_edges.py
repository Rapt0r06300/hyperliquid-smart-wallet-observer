from __future__ import annotations

from types import SimpleNamespace

import pytest

import hl_observer.ui.status_routes as status


def test_env_and_numeric_helpers(monkeypatch) -> None:
    monkeypatch.setenv("X_BOOL", " YES ")
    monkeypatch.setenv("X_OFF", "off")
    monkeypatch.setenv("X_INT", "12.9")
    monkeypatch.setenv("X_FLOAT", "1.25")
    assert status._env_truthy("X_BOOL") is True
    assert status._env_disabled("X_OFF") is True
    assert status._env_int("X_INT", 3) == 12
    assert status._env_float("X_FLOAT", 3.0) == 1.25
    monkeypatch.setenv("X_INT", "bad")
    monkeypatch.setenv("X_FLOAT", "bad")
    assert status._env_int("X_INT", 7) == 7
    assert status._env_float("X_FLOAT", 2.5) == 2.5
    assert status._safe_int("4") == 4
    assert status._safe_int("bad") is None
    assert status._safe_float("4.5") == 4.5
    assert status._safe_float(None) is None


def test_coin_cleaning_inference_and_position_normalisation() -> None:
    assert status._clean_status_coin(" btc-usdt ") == "BTC"
    assert status._clean_status_coin("ETH/USD") == "ETH"
    assert status._clean_status_coin("LONG") == ""
    assert status._clean_status_coin("0x123456789abcdef") == ""
    assert status._clean_status_coin("bad coin!") == ""
    assert status._clean_status_coin("?") == ""
    assert status._infer_status_coin({"position_id": "wallet|PAXG|LONG"}, index=0) == "PAXG"
    assert status._infer_status_coin({"coin": "sol-usd"}, index=0) == "SOL"
    assert status._infer_status_coin({}, index=0) == ""

    normalized = status._normalize_position_for_status(
        {
            "position_id": "p1",
            "coin": "BTC",
            "size": -2,
            "entry_price": 100,
            "leader_wallets_csv": "a,b",
            "strategy_family": "manual",
        },
        index=0,
    )
    assert normalized["coin"] == "BTC"
    assert normalized["direction"] == "SHORT"
    assert normalized["size"] == 2.0
    assert normalized["leader_wallets_count"] == 2
    assert status._is_valid_status_position(normalized) is True
    assert status._is_valid_status_position({"coin": "BTC", "direction": "LONG", "size": 0, "entry_price": 1}) is False


def test_latest_mid_prices_and_snapshot_merge() -> None:
    assert status._latest_mid_prices_from_snapshot(None) == {}
    assert status._latest_mid_prices_from_snapshot({"prices": {"btc": "100", "ETH": -1, "BAD": "x"}}) == {"BTC": 100.0}
    assert status._latest_mid_prices_from_snapshot({"sol": 20}) == {"SOL": 20.0}

    snapshots = [
        SimpleNamespace(exchange_ts=100, id=1, raw_json={"prices": {"BTC": 100}}, source="old"),
        SimpleNamespace(exchange_ts=200, id=2, raw_json={"prices": {"BTC": 101, "ETH": 50}}, source="new"),
    ]
    marks = status._latest_market_marks_from_snapshots(snapshots)
    assert marks["prices"] == {"BTC": 101.0, "ETH": 50.0}
    assert marks["sources"] == {"BTC": "new", "ETH": "new"}
    assert marks["latest_exchange_ts"] == 200
    assert marks["read_status"] == "OK"
    assert status._latest_market_marks_from_snapshots([])["read_status"] == "NO_USABLE_MARK"


def test_empty_merge_and_live_mark_projection() -> None:
    empty = status._empty_market_marks("NO_DATA", error="x")
    assert empty["prices"] == {}
    assert empty["read_status"] == "NO_DATA"
    assert empty["error"] == "x"

    merged = status._merge_market_marks(
        {
            "prices": {"BTC": 101.0},
            "sources": {"BTC": "primary"},
            "timestamps": {"BTC": 200},
            "latest_exchange_ts": 200,
            "read_status": "PRIMARY",
        },
        {
            "prices": {"BTC": 99.0, "ETH": 50.0},
            "sources": {"BTC": "fallback", "ETH": "fallback"},
            "latest_exchange_ts": 100,
            "read_status": "FALLBACK",
        },
    )
    assert merged["prices"] == {"BTC": 101.0, "ETH": 50.0}
    assert merged["sources"]["BTC"] == "primary"
    assert merged["timestamps"]["ETH"] == 100
    assert merged["latest_exchange_ts"] == 200
    assert merged["read_status"] == "PRIMARY"

    live = status._marks_from_live_prices(
        {"BTC": 100.0, "ETH": 50.0}, {"BTC", "SOL"}, 1234, read_status="LIVE"
    )
    assert live["prices"] == {"BTC": 100.0}
    assert live["read_status"] == "LIVE"
    no_match = status._marks_from_live_prices({"ETH": 50.0}, {"BTC"}, 1234, read_status="LIVE")
    assert no_match["read_status"] == "LIVE_ALLMIDS_NO_MATCHING_MARK"


def test_mark_age_flat_reason_and_diagnostics() -> None:
    marks = {"timestamps": {"BTC": 900}, "latest_exchange_ts": 800, "read_status": "OK"}
    assert status._mark_age_ms(marks, 1000, key="BTC") == 100
    assert status._mark_age_ms(marks, 1000, key="ETH") == 200
    assert status._mark_age_ms({}, 1000) is None
    assert status._mark_age_ms({"latest_exchange_ts": 1100}, 1000) == 0
    assert status._flat_graph_reason("OK", 1) == "NO_REAL_MARK_FOR_OPEN_POSITION"
    assert status._flat_graph_reason("NO_OPEN_POSITION", 0) == "NO_OPEN_PAPER_POSITION"
    assert status._flat_graph_reason("CUSTOM", 0) == "CUSTOM"

    diagnostics = status._build_mark_diagnostics(
        positions=[
            {
                "position_id": "p1",
                "coin": "BTC",
                "direction": "LONG",
                "entry_price": 100,
                "mark_price": 101,
                "market_mark_available": True,
            }
        ],
        market_marks=marks,
        current_ms=1000,
        marks_used=1,
        marks_missing=0,
        invalid_positions=[{"position_id": "bad"}],
    )
    assert diagnostics["graph_should_move"] is True
    assert diagnostics["flat_graph_reason"] is None
    assert diagnostics["invalid_positions_skipped"] == 1
    assert diagnostics["positions"][0]["reason"] == "OK_REAL_MARK"


def test_mark_to_market_long_short_missing_and_invalid_positions() -> None:
    raw = [
        {"position_id": "long", "coin": "BTC", "direction": "LONG", "size": 1, "entry_price": 100},
        {"position_id": "short", "coin": "ETH", "direction": "SHORT", "size": 2, "entry_price": 50},
        {"position_id": "missing", "coin": "SOL", "direction": "LONG", "size": 1, "entry_price": 20},
        {"position_id": "invalid", "coin": "?", "direction": "LONG", "size": 1, "entry_price": 20},
    ]
    marks = {
        "prices": {"BTC|LONG": 110.0, "ETH|SHORT": 45.0},
        "sources": {"BTC|LONG": "bid", "ETH|SHORT": "ask"},
        "timestamps": {"BTC|LONG": 900, "ETH|SHORT": 900},
        "latest_exchange_ts": 900,
        "read_status": "OK",
    }
    result = status._mark_to_market_positions(
        raw,
        starting_equity_usdt=1000.0,
        realized_pnl_usdc=1.0,
        market_marks=marks,
        current_ms=1000,
    )
    assert result["marks_used"] == 2
    assert result["marks_missing"] == 1
    assert result["mark_to_market"]["invalid_positions_skipped"] == 1
    assert len(result["positions"]) == 3
    by_id = {row["position_id"]: row for row in result["positions"]}
    assert by_id["long"]["gross_unrealized_pnl_usdc"] == pytest.approx(10.0)
    assert by_id["short"]["gross_unrealized_pnl_usdc"] == pytest.approx(10.0)
    assert by_id["missing"]["market_mark_available"] is False


def test_history_cleanup_dedup_and_fast_append() -> None:
    history = [
        {"timestamp_ms": 1, "source": "MARK_TO_MARKET"},
        {"timestamp_ms": 2, "source": "A", "current_equity_usdt": 1000},
        {"timestamp_ms": 2, "source": "B", "current_equity_usdt": 1001},
        {"timestamp_ms": 1, "source": "C", "current_equity_usdt": 1002},
        {"source": "invalid"},
    ]
    status._drop_legacy_overview_equity_points(history)
    assert all(row.get("source") != "MARK_TO_MARKET" for row in history)
    status._dedupe_equity_history_timestamps(history)
    assert [row["timestamp_ms"] for row in history] == [2, 3]

    state = SimpleNamespace(simulation_equity_history=[])
    marked = {
        "estimated_net_pnl_usdc": 1,
        "current_equity_usdt": 1001,
        "realized_pnl_usdc": 0.4,
        "unrealized_pnl_usdc": 0.6,
        "open_exposure_usdt": 100,
        "positions": [{"coin": "BTC"}],
        "marks_used": 1,
        "marks_missing": 0,
    }
    status._append_fast_equity_point(None, state, marked, 1000)
    assert len(state.simulation_equity_history) == 1
    assert state.simulation_equity_history[0]["source"] == "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID"
    status._append_fast_equity_point(None, state, marked, 1000)
    assert len(state.simulation_equity_history) == 1


def test_scanner_and_entry_supply_cover_all_bottlenecks() -> None:
    no_data = status._entry_supply_status(
        wallet_candidates_total=0,
        public_trade_events=0,
        position_deltas_total=0,
        fresh_entry_deltas=0,
        virtual_entries=0,
        virtual_refusals=0,
    )
    supply = status._entry_supply_status(
        wallet_candidates_total=2,
        public_trade_events=1,
        position_deltas_total=0,
        fresh_entry_deltas=0,
        virtual_entries=0,
        virtual_refusals=0,
    )
    gates = status._entry_supply_status(
        wallet_candidates_total=2,
        public_trade_events=1,
        position_deltas_total=2,
        fresh_entry_deltas=1,
        virtual_entries=0,
        virtual_refusals=3,
    )
    ok = status._entry_supply_status(
        wallet_candidates_total=2,
        public_trade_events=1,
        position_deltas_total=2,
        fresh_entry_deltas=1,
        virtual_entries=1,
        virtual_refusals=0,
    )
    assert {no_data["severity"], supply["severity"], gates["severity"], ok["severity"]} == {"error", "warning", "ok"}
    assert len({no_data["bottleneck"], supply["bottleneck"], gates["bottleneck"], ok["bottleneck"]}) == 4

    engine = {
        "available": True,
        "updated_at_ms": 900,
        "phase": "running",
        "poll_index": "2",
        "metrics": {
            "selected_top_wallets": "3",
            "public_trade_candidates": 4,
            "public_trade_events": 5,
            "recent_deltas": 6,
            "fresh_entry_deltas": 1,
            "virtual_entries_logged": 0,
            "virtual_refusals_logged": 2,
        },
    }
    scanner = status._scanner_payload_from_engine_status(engine, 1000)
    assert scanner["engine_running"] is True
    assert scanner["leaders_selected"] == 3
    assert scanner["wallet_candidates_total"] == 4
    assert scanner["entry_supply"]["bottleneck"] == gates["bottleneck"]

    stale = status._scanner_payload_from_engine_status({"available": True, "updated_at_ms": 0, "phase": "finished"}, 100000)
    assert stale["engine_running"] is False
    assert status._metric_int({"x": "bad", "y": 5}, "x", "y") == 5
    assert status._metric_int({}, "x") == 0
