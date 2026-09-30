from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient
from hl_observer.signals.position_delta_detector import reconstruct_position_deltas_from_fills
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import (
    CollectionRun,
    Fill,
    OpenOrder,
    Position,
    PositionDeltaModel,
    RawEvent,
    Wallet,
    WalletActivitySummary,
    WalletBackfillRun,
    WalletCoinProfileModel,
)
from hl_observer.wallets.backfill import WalletBackfillPlan, run_wallet_backfill

VALID_WALLET = "0x" + "2" * 40


def _settings_for_db(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'wallet_backfill.sqlite3'}"
    return settings


def _session_factory(database_url: str) -> sessionmaker:
    init_db(database_url)
    return create_session_factory(create_sqlite_engine(database_url))


def _mock_client(handler) -> HyperliquidInfoClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return HyperliquidInfoClient(
        "https://api.hyperliquid.xyz/info",
        max_retries=0,
        client=http_client,
    )


def _request_json(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode())


def test_wallet_backfill_dry_run_no_network(monkeypatch):
    class ExplodingClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("network client should not be constructed in dry-run")

    monkeypatch.setattr("hl_observer.wallets.backfill.HyperliquidInfoClient", ExplodingClient)
    runner = CliRunner()

    result = runner.invoke(app, ["wallet-backfill", "--wallet", VALID_WALLET, "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "dry-run: no network and no database writes" in result.output
    assert f"userFills:{VALID_WALLET}" in result.output


def test_wallet_backfill_rejects_invalid_wallet_address():
    runner = CliRunner()

    result = runner.invoke(app, ["wallet-backfill", "--wallet", "0x123", "--fetch"])

    assert result.exit_code != 0
    assert "wallet address must be 0x followed by 40 hex characters" in result.output


def test_wallet_backfill_rejects_invalid_wallet():
    runner = CliRunner()

    result = runner.invoke(app, ["wallet-backfill", "--wallet", "not-a-wallet"])

    assert result.exit_code != 0
    assert "wallet address must be 0x followed by 40 hex characters" in result.output


def test_wallet_backfill_fetch_stores_fills_and_position_deltas(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)
    fills = [
        {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "1", "startPosition": "0"},
        {"coin": "BTC", "time": 2000, "side": "A", "px": "110", "sz": "0.4", "startPosition": "1"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _request_json(request)
        assert request.url.path == "/info"
        assert payload["type"] == "userFills"
        return httpx.Response(200, json=fills)

    result = asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                include_fills_by_time=False,
                include_open_orders=False,
                include_frontend_open_orders=False,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        wallet = session.get(Wallet, VALID_WALLET)
        stored_fills = session.query(Fill).order_by(Fill.exchange_ts).all()
        deltas = session.query(PositionDeltaModel).order_by(PositionDeltaModel.exchange_ts).all()
        positions = session.query(Position).all()
        backfill_run = session.query(WalletBackfillRun).one()
        summary = session.query(WalletActivitySummary).one()
        raw = session.query(RawEvent).one()
        run = session.query(CollectionRun).one()

    assert result.fills_stored == 2
    assert result.position_deltas_created == 2
    assert wallet is not None
    assert [delta.delta_type for delta in deltas] == ["open_long", "reduce_long"]
    assert [delta.action for delta in deltas] == ["OPEN", "REDUCE"]
    assert all(delta.confidence_score > 0 for delta in deltas)
    assert positions[0].confidence_score > 0
    assert backfill_run.status == "SUCCESS"
    assert summary.open_count == 1
    assert stored_fills[0].fill_hash
    assert raw.request_type == "userFills"
    assert run.success


def test_wallet_backfill_fetches_user_fills_by_time(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)
    seen_types: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _request_json(request)
        seen_types.append(payload["type"])
        return httpx.Response(
            200,
            json=[{"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "1"}],
        )

    asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                start_ms=1,
                end_ms=2,
                limit_pages=1,
                include_recent_fills=False,
                include_open_orders=False,
                include_frontend_open_orders=False,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    assert seen_types == ["userFillsByTime"]


def test_wallet_backfill_stores_raw_events(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                include_recent_fills=True,
                include_fills_by_time=False,
                include_open_orders=False,
                include_frontend_open_orders=False,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        raw = session.query(RawEvent).one()

    assert raw.request_type == "userFills"
    assert raw.wallet_address == VALID_WALLET
    assert raw.response_hash


def test_wallet_backfill_stores_open_orders(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _request_json(request)
        assert payload["type"] == "openOrders"
        return httpx.Response(200, json=[{"coin": "BTC", "oid": 123, "cloid": "abc"}])

    asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                include_recent_fills=False,
                include_fills_by_time=False,
                include_open_orders=True,
                include_frontend_open_orders=False,
                rebuild_positions=False,
                compute_position_deltas=False,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        order = session.query(OpenOrder).one()

    assert order.wallet_address == VALID_WALLET
    assert order.coin == "BTC"


def test_wallet_backfill_report_outputs_summary():
    runner = CliRunner()

    result = runner.invoke(app, ["wallet-backfill", "--wallet", VALID_WALLET, "--dry-run", "--report"])

    assert result.exit_code == 0, result.output
    assert "wallet-backfill report" in result.output
    assert "fills stored:" in result.output


def test_wallet_backfill_never_calls_exchange(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json=[])

    asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                include_recent_fills=True,
                include_fills_by_time=False,
                include_open_orders=True,
                include_frontend_open_orders=True,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    assert seen_paths
    assert set(seen_paths) == {"/info"}


def test_wallet_backfill_user_fills_by_time_respects_max_pages(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = _request_json(request)
        assert payload["type"] == "userFillsByTime"
        return httpx.Response(
            200,
            json=[
                {
                    "coin": "ETH",
                    "time": payload["startTime"],
                    "side": "B",
                    "px": "10",
                    "sz": "1",
                    "startPosition": "0",
                }
            ],
        )

    result = asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                start_ms=1,
                end_ms=5000,
                page_window_ms=1000,
                limit_pages=2,
                include_recent_fills=False,
                include_open_orders=False,
                include_frontend_open_orders=False,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    assert calls == 2
    assert result.fetched_items == 2
    assert result.position_deltas_created == 2


def test_wallet_backfill_deduplicates_same_fill_for_deltas(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "1", "startPosition": "0"}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _request_json(request)
        assert payload["type"] in {"userFills", "userFillsByTime"}
        return httpx.Response(200, json=[fill])

    result = asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                start_ms=1,
                end_ms=1000,
                page_window_ms=1000,
                limit_pages=1,
                include_open_orders=False,
                include_frontend_open_orders=False,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        fills_count = session.query(Fill).count()
        deltas_count = session.query(PositionDeltaModel).count()

    assert result.fills_stored == 1
    assert result.position_deltas_created == 1
    assert fills_count == 1
    assert deltas_count == 1


def test_position_delta_reconstruction_uses_start_position():
    deltas = reconstruct_position_deltas_from_fills(
        VALID_WALLET,
        [{"coin": "BTC", "time": 1, "side": "A", "sz": "0.5", "startPosition": "1.5"}],
    )

    assert len(deltas) == 1
    assert deltas[0].previous_size == 1.5
    assert deltas[0].current_size == 1.0
    assert deltas[0].delta_type == "reduce_long"
    assert deltas[0].confidence == "high"


def test_position_delta_reconstruction_without_start_position_is_medium_confidence():
    deltas = reconstruct_position_deltas_from_fills(
        VALID_WALLET,
        [
            {"coin": "BTC", "time": 1, "side": "B", "sz": "1"},
            {"coin": "BTC", "time": 2, "side": "A", "sz": "0.25"},
        ],
    )

    assert [delta.current_size for delta in deltas] == [1.0, 0.75]
    assert {delta.confidence for delta in deltas} == {"medium"}


def test_wallet_backfill_keeps_all_fill_coins(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)
    fills = [
        {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "1", "startPosition": "0"},
        {"coin": "SOL", "time": 2000, "side": "B", "px": "20", "sz": "3", "startPosition": "0"},
        {"coin": "HYPE", "time": 3000, "side": "B", "px": "5", "sz": "5", "startPosition": "0"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fills)

    result = asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                include_fills_by_time=False,
                include_open_orders=False,
                include_frontend_open_orders=False,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        coins = {fill.coin for fill in session.query(Fill).all()}

    assert coins == {"BTC", "SOL", "HYPE"}
    assert result.fills_by_coin == {"BTC": 1, "SOL": 1, "HYPE": 1}


def test_wallet_backfill_reconstructs_deltas_by_coin(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)
    fills = [
        {"coin": "SOL", "time": 1000, "side": "B", "px": "20", "sz": "1", "startPosition": "0"},
        {"coin": "HYPE", "time": 2000, "side": "B", "px": "5", "sz": "1", "startPosition": "0"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fills)

    result = asyncio.run(
        run_wallet_backfill(
            WalletBackfillPlan(
                fetch=True,
                wallets=[VALID_WALLET],
                include_fills_by_time=False,
                include_open_orders=False,
                include_frontend_open_orders=False,
            ),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        deltas = session.query(PositionDeltaModel).all()
        profiles = session.query(WalletCoinProfileModel).all()

    assert {delta.coin for delta in deltas} == {"SOL", "HYPE"}
    assert result.deltas_by_coin == {"SOL": 1, "HYPE": 1}
    assert {profile.coin for profile in profiles} == {"SOL", "HYPE"}
