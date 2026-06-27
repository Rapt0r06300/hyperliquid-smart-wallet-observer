from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketSnapshot, PositionDeltaModel, TopWallet
from hl_observer.ui.app import create_ui_app
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


def test_simulation_dedupes_same_fill_between_poll_rows(tmp_path: Path):
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
