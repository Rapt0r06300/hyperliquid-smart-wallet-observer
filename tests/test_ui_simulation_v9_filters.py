from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketSnapshot, PositionDeltaModel, TopWallet
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.simulation_log_export import LOGS_TO_SEND_DIRNAME
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


def _client(tmp_path: Path) -> tuple[TestClient, object, UiState]:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_v9_filters.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.simulation_started_at_ms = now_ms() - 3_600_000
    client = TestClient(create_ui_app(settings, state))
    factory = create_session_factory(create_sqlite_engine(settings.database_url))
    return client, factory, state


def test_simulation_overview_uses_snapshot_when_runtime_db_is_huge(tmp_path: Path, monkeypatch):
    settings = load_settings()
    db_path = tmp_path / "data" / "huge_runtime.sqlite3"
    settings.database_url = f"sqlite:///{db_path}"
    settings.logs_dir = str(tmp_path / "logs")
    init_db(settings.database_url)
    # The production incident is a multi-GB runtime DB. This test inflates the
    # temp DB just enough to trigger the same fast snapshot path without reading
    # the corrupt/inflated file again.
    with db_path.open("ab") as handle:
        handle.write(b"0" * (2 * 1024 * 1024))
    logs_to_send = Path(settings.logs_dir) / LOGS_TO_SEND_DIRNAME
    logs_to_send.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "mode": "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA",
        "bot_simulation": {
            "current_equity_usdt": 1001.25,
            "estimated_net_pnl_usdc": 1.25,
            "open_positions": [{"coin": "BTC"}, {"coin": "ETH"}],
            "events": [{"coin": "BTC"}, {"coin": "ETH"}, {"coin": "SOL"}],
        },
        "leaders": [{"wallet_address": "0x" + "1" * 40}, {"wallet_address": "0x" + "2" * 40}],
    }
    (logs_to_send / "simulation_snapshot_latest.json").write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_SNAPSHOT", "1")
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_DB_THRESHOLD_MB", "1")

    client = TestClient(create_ui_app(settings, UiState()))
    payload = client.get("/api/simulation/overview?limit=1").json()

    assert payload["overview_fast_snapshot"] is True
    assert payload["bot_simulation"]["current_equity_usdt"] == 1001.25
    assert len(payload["bot_simulation"]["events"]) == 1
    assert len(payload["leaders"]) == 1


def test_simulation_overview_huge_db_uses_live_state_when_snapshot_is_stale_or_empty(tmp_path: Path, monkeypatch):
    settings = load_settings()
    db_path = tmp_path / "data" / "huge_runtime_live_state.sqlite3"
    settings.database_url = f"sqlite:///{db_path}"
    settings.logs_dir = str(tmp_path / "logs")
    init_db(settings.database_url)
    with db_path.open("ab") as handle:
        handle.write(b"0" * (2 * 1024 * 1024))
    logs_to_send = Path(settings.logs_dir) / LOGS_TO_SEND_DIRNAME
    logs_to_send.mkdir(parents=True, exist_ok=True)
    stale_snapshot = logs_to_send / "simulation_snapshot_latest.json"
    stale_snapshot.write_text(json.dumps({"mode": "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA"}), encoding="utf-8")
    os.utime(stale_snapshot, (1, 1))
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 2.5
    state.simulation_virtual_positions = {
        "paper-pos-1": {
            "coin": "HYPE",
            "side": "LONG",
            "entry_price": 40.0,
            "size": 1.0,
            "unrealized_pnl_usdc": 0.5,
        }
    }
    state.simulation_equity_history = [
        {
            "timestamp_ms": 1_800_000_000_000,
            "current_equity_usdt": 1003.0,
            "current_pnl_usdc": 3.0,
            "realized_pnl_usdc": 2.5,
            "unrealized_pnl_usdc": 0.5,
            "open_exposure_usdt": 40.0,
        }
    ]
    state.simulation_ledger_events = [
        {
            "delta_key": "paper-close-1",
            "observed_at_ms": 1_800_000_000_000,
            "coin": "HYPE",
            "paper_action_type": "CLOSE",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "estimated_net_pnl_usdc": 2.5,
            "paper_position_instance_id": "paper-pos-closed-1",
        }
    ]
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_SNAPSHOT", "1")
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_DB_THRESHOLD_MB", "1")

    client = TestClient(create_ui_app(settings, state))
    payload = client.get("/api/simulation/overview?limit=5").json()

    assert payload["overview_fast_state"] is True
    assert payload["overview_fast_snapshot"] is False
    assert payload["equity"]["current_equity_usdt"] == 1003.0
    assert payload["bot_simulation"]["current_equity_usdt"] == 1003.0
    assert payload["paper_ledger"]["closed_trade_stats"]["winning_trades"] == 1
    assert payload["bot_simulation"]["closed_trades"] == 1
    exported = json.loads(stale_snapshot.read_text(encoding="utf-8"))
    assert exported["bot_simulation"]["current_equity_usdt"] == 1003.0
    assert exported["paper_ledger"]["closed_trade_stats"]["winning_trades"] == 1


def _leader(wallet: str, *, rank: int = 1, ts: int = 1) -> TopWallet:
    return TopWallet(
        wallet_address=wallet,
        rank=rank,
        source="public_trades_ws",
        score=95.0,
        selected_at_ms=ts,
        status="selected",
    )


def _open_delta(wallet: str, *, coin: str = "ETH", ts: int, raw: dict | None = None, source: str = "hyperliquid_ws:userFills") -> PositionDeltaModel:
    return PositionDeltaModel(
        wallet_address=wallet,
        coin=coin,
        previous_side="FLAT",
        new_side="LONG",
        previous_size=0.0,
        current_size=2.0,
        new_size=2.0,
        delta_size=2.0,
        delta_notional_usdc=6_000.0,
        action="OPEN",
        exchange_ts=ts,
        detected_at_ms=ts,
        source=source,
        side="B",
        price=3_000.0,
        fill_size=2.0,
        delta_type="open_long",
        confidence="high",
        confidence_score=0.95,
        is_paper_eligible=True,
        raw_json=raw or {"coin": coin, "dir": "Open Long"},
    )


def test_simulation_skips_exotic_markets_without_no_trade_noise(tmp_path: Path):
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet = "0x" + "1" * 40
    with factory() as session:
        session.add(_leader(wallet, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"XYZ:TSLA": "3000"}))
        session.add(_open_delta(wallet, coin="XYZ:TSLA", ts=ts))
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 0
    assert payload["bot_simulation"]["filter_diagnostics"]["exotic_market_skipped"] == 1
    assert payload["bot_simulation"]["prefilter_skip_count"] == 1
    assert payload["bot_simulation"]["prefilter_skips"][0]["reason"] == "EXOTIC_MARKET_SKIPPED"
    assert payload["scanner"]["entry_supply"]["bottleneck"] == "NO_DATA"
    assert all(row.get("coin") != "XYZ:TSLA" for row in payload["bot_simulation"]["events"])


def test_simulation_skips_old_rest_backfill_before_scoring(tmp_path: Path):
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    old_fill_ts = ts - 5 * 60 * 60 * 1000
    wallet = "0x" + "2" * 40
    with factory() as session:
        session.add(_leader(wallet, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        row = _open_delta(
            wallet,
            ts=old_fill_ts,
            source="hyperliquid_rest:userFillsByTime",
            raw={"coin": "ETH", "dir": "Open Long", "time": old_fill_ts, "hash": "old-rest-fill"},
        )
        row.detected_at_ms = ts
        session.add(row)
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 0
    assert payload["bot_simulation"]["filter_diagnostics"]["hard_stale_entry_skipped"] == 1
    assert payload["bot_simulation"]["prefilter_skip_count"] == 1
    assert payload["bot_simulation"]["prefilter_skips"][0]["reason"] == "STALE_BACKFILL"
    assert payload["bot_simulation"]["prefilter_skips"][0]["signal_age_ms"] >= 5 * 60 * 60 * 1000
    assert payload["scanner"]["entry_supply"]["bottleneck"] == "SUPPLY"
    assert payload["scanner"]["entry_supply"]["prefilter_skips"] == 1
    assert all((row.get("signal_age_ms") or 0) <= 60_000 for row in payload["bot_simulation"]["events"])


def test_simulation_dedupes_same_fill_between_poll_rows(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "1")
    monkeypatch.setenv("HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS", "5")
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet = "0x" + "3" * 40
    raw = {"coin": "ETH", "dir": "Open Long", "hash": "same-fill", "tid": 11, "oid": 22, "time": ts}
    with factory() as session:
        session.add(_leader(wallet, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        session.add(_open_delta(wallet, ts=ts, raw=raw))
        session.add(_open_delta(wallet, ts=ts + 1, raw=raw))
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 1
    assert payload["scanner"]["entry_supply"]["bottleneck"] == "OK"
    assert payload["scanner"]["entry_supply"]["accepted_entries"] == 1
    assert payload["bot_simulation"]["filter_diagnostics"]["duplicate_delta_skipped"] == 1


def test_simulation_skips_orphan_reduce_without_ledger_noise(tmp_path: Path):
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet = "0x" + "4" * 40
    with factory() as session:
        session.add(_leader(wallet, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side="LONG",
                new_side="LONG",
                previous_size=2.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=-1.0,
                delta_notional_usdc=3_000.0,
                action="REDUCE",
                exchange_ts=ts,
                detected_at_ms=ts,
                source="hyperliquid_ws:userFills",
                side="A",
                price=3_000.0,
                fill_size=1.0,
                delta_type="reduce_long",
                confidence="high",
                confidence_score=0.95,
                raw_json={"coin": "ETH", "dir": "Close Long", "hash": "orphan-reduce", "time": ts},
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 0
    assert payload["bot_simulation"]["filter_diagnostics"]["orphan_exit_skipped"] == 1
    assert payload["bot_simulation"]["prefilter_skip_count"] == 1
    assert payload["bot_simulation"]["prefilter_skips"][0]["reason"] == "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
    assert payload["scanner"]["entry_supply"]["bottleneck"] == "SUPPLY"
    assert "NO_MATCHING_PAPER_POSITION_FOR_CLOSE" not in {
        str(row.get("reason") or "") for row in payload["bot_simulation"]["events"]
    }


def test_accepted_fresh_opportunity_cluster_opens_virtual_position_with_v9_authoritative(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("HYPERSMART_V9_PIPELINE_AUTHORITATIVE", "1")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "5")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "30000")
    monkeypatch.setenv("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "2")
    monkeypatch.setenv("HYPERSMART_RUNTIME_DEPTH_FILL_GUARD", "0")
    monkeypatch.setenv("HYPERSMART_RUNTIME_MICROSTRUCTURE_GUARD", "0")
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    with factory() as session:
        session.add(_leader(wallet_a, rank=1, ts=ts))
        session.add(_leader(wallet_b, rank=2, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        session.add(
            _open_delta(
                wallet_a,
                ts=ts - 2_000,
                raw={"coin": "ETH", "dir": "Open Long", "hash": "fresh-cluster-a", "time": ts - 2_000},
                source="hyperliquid_ws:userFills",
            )
        )
        session.add(
            _open_delta(
                wallet_b,
                ts=ts - 1_000,
                raw={"coin": "ETH", "dir": "Open Long", "hash": "fresh-cluster-b", "time": ts - 1_000},
                source="hyperliquid_ws:userFills",
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=40").json()

    accepted_fresh = [
        row for row in payload["fresh_opportunities"]
        if row.get("decision") == "ACCEPT_LOCAL_SIMULATION"
    ]
    assert accepted_fresh
    assert payload["counts"]["reproduced_entries"] >= 1
    assert payload["bot_simulation"]["open_positions"], payload["bot_simulation"]["events"]
    accepted_events = [
        row for row in payload["bot_simulation"]["events"]
        if row.get("status") == "LOCAL_REPLAY"
    ]
    assert accepted_events
    assert any(row.get("position_mode") == "CONSENSUS_CLUSTER" for row in accepted_events)
