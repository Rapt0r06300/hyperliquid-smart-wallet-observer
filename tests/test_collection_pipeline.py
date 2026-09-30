from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.collection.collector import CollectionPlan, run_collection_once
from hl_observer.config.loader import load_settings
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import (
    ApiHealth,
    CollectionRun,
    Fill,
    MarketSnapshot,
    OrderbookSnapshot,
    RawEvent,
)
from hl_observer.storage.repositories import stable_payload_hash

VALID_WALLET = "0x" + "1" * 40


def _settings_for_db(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'collection.sqlite3'}"
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


def test_collect_once_dry_run_no_network(monkeypatch):
    class ExplodingClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("network client should not be constructed in dry-run")

    monkeypatch.setattr("hl_observer.collection.collector.HyperliquidInfoClient", ExplodingClient)
    runner = CliRunner()

    result = runner.invoke(app, ["collect-once", "--dry-run", "--all-mids", "--coin", "BTC"])

    assert result.exit_code == 0, result.output
    assert "dry-run: no network and no database writes" in result.output
    assert "allMids" in result.output


def test_collect_once_fetch_all_mids_stores_raw_event(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/info"
        assert _request_json(request)["type"] == "allMids"
        return httpx.Response(200, json={"BTC": "100.0", "ETH": "10.0"})

    result = asyncio.run(
        run_collection_once(
            CollectionPlan(fetch=True, all_mids=True),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        raw = session.query(RawEvent).one()
        snapshot = session.query(MarketSnapshot).one()

    assert result.raw_events_stored == 1
    assert raw.request_type == "allMids"
    assert raw.success
    assert snapshot.raw_json["BTC"] == "100.0"


def test_collect_once_fetch_l2_book_stores_orderbook(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)
    response = {
        "coin": "BTC",
        "levels": [
            [{"px": "99", "sz": "2"}],
            [{"px": "101", "sz": "3"}],
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _request_json(request)
        assert payload == {"type": "l2Book", "coin": "BTC"}
        return httpx.Response(200, json=response)

    asyncio.run(
        run_collection_once(
            CollectionPlan(fetch=True, coins=["BTC"], l2_book=True),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        book = session.query(OrderbookSnapshot).one()
        raw = session.query(RawEvent).one()

    assert book.coin == "BTC"
    assert book.depth_usdc == 501
    assert book.spread_bps == 200
    assert raw.request_type == "l2Book"


def test_collect_once_fetch_user_fills_stores_raw_event(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)

    def handler(request: httpx.Request) -> httpx.Response:
        assert _request_json(request)["type"] == "userFills"
        return httpx.Response(200, json=[{"coin": "BTC", "time": 123, "side": "B", "px": "100", "sz": "1"}])

    asyncio.run(
        run_collection_once(
            CollectionPlan(fetch=True, wallets=[VALID_WALLET], user_fills=True),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        raw = session.query(RawEvent).one()
        fill = session.query(Fill).one()

    assert raw.wallet_address == VALID_WALLET
    assert raw.request_type == "userFills"
    assert fill.wallet_address == VALID_WALLET
    assert fill.coin == "BTC"


def test_user_fills_by_time_pagination_stops_on_empty():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert _request_json(request)["type"] == "userFillsByTime"
        return httpx.Response(200, json=[])

    async def run():
        client = _mock_client(handler)
        pages = []
        async for page in client.iter_user_fills_by_time(
            VALID_WALLET,
            1,
            10_000,
            page_window_ms=1000,
            max_pages=5,
        ):
            pages.append(page)
        await client._client.aclose()  # type: ignore[union-attr]
        return pages

    assert asyncio.run(run()) == []
    assert calls == 1


def test_user_fills_by_time_pagination_respects_max_pages():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[{"time": calls * 1000, "coin": "BTC"}])

    async def run():
        client = _mock_client(handler)
        pages = []
        async for page in client.iter_user_fills_by_time(
            VALID_WALLET,
            1,
            10_000,
            page_window_ms=1000,
            max_pages=2,
        ):
            pages.append(page)
        await client._client.aclose()  # type: ignore[union-attr]
        return pages

    pages = asyncio.run(run())

    assert len(pages) == 2
    assert calls == 2


def test_collect_once_rejects_invalid_wallet_address():
    runner = CliRunner()

    result = runner.invoke(app, ["collect-once", "--fetch", "--wallet", "0x123", "--user-fills"])

    assert result.exit_code != 0
    assert "wallet address must be 0x followed by 40 hex characters" in result.output


def test_rest_info_client_never_calls_exchange():
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"BTC": "100"})

    async def run():
        client = _mock_client(handler)
        await client.all_mids()
        await client._client.aclose()  # type: ignore[union-attr]

    asyncio.run(run())

    assert seen_paths == ["/info"]
    assert not hasattr(HyperliquidInfoClient, "exchange")


def test_raw_event_response_hash_stable():
    assert stable_payload_hash({"b": 2, "a": 1}) == stable_payload_hash({"a": 1, "b": 2})


def test_api_error_is_stored(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    result = asyncio.run(
        run_collection_once(
            CollectionPlan(fetch=True, all_mids=True),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        raw = session.query(RawEvent).one()
        health = session.query(ApiHealth).one()
        run = session.query(CollectionRun).one()

    assert result.errors_count == 1
    assert not raw.success
    assert not health.ok
    assert not run.success


def test_collection_run_records_success(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"BTC": "100"})

    asyncio.run(
        run_collection_once(
            CollectionPlan(fetch=True, all_mids=True),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        run = session.query(CollectionRun).one()

    assert run.success
    assert run.errors_count == 0
    assert run.finished_at_ms is not None


def test_collection_run_records_failure(tmp_path):
    settings = _settings_for_db(tmp_path)
    session_factory = _session_factory(settings.database_url)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    asyncio.run(
        run_collection_once(
            CollectionPlan(fetch=True, all_mids=True),
            settings,
            client=_mock_client(handler),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        run = session.query(CollectionRun).one()

    assert not run.success
    assert run.errors_count == 1
