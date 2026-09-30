from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from hl_observer.config.loader import load_settings
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient
from hl_observer.markets.coin_metrics import build_market_metric
from hl_observer.markets.scanner import MarketScanPlan, run_scan_markets
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketMetric


def _settings(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'markets.sqlite3'}"
    settings.market_universe.max_l2book_coins_per_scan = 10
    init_db(settings.database_url)
    return settings


def _mock_client(handler) -> HyperliquidInfoClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return HyperliquidInfoClient("https://api.hyperliquid.xyz/info", max_retries=0, client=http_client)


def _payload(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode())


def _book(coin: str) -> dict[str, Any]:
    return {"coin": coin, "levels": [[{"px": "99", "sz": "100"}], [{"px": "101", "sz": "100"}]]}


def test_scan_markets_scans_multiple_coins(tmp_path):
    settings = _settings(tmp_path)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _payload(request)
        seen.append(payload["type"])
        if payload["type"] == "meta":
            return httpx.Response(200, json={"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}]})
        if payload["type"] == "allMids":
            return httpx.Response(200, json={"BTC": "100", "ETH": "50", "SOL": "25"})
        if payload["type"] == "l2Book":
            return httpx.Response(200, json=_book(payload["coin"]))
        raise AssertionError(payload)

    result = asyncio.run(
        run_scan_markets(
            MarketScanPlan(all_coins=True, max_coins=3, store=True, dry_run=False),
            settings,
            client=_mock_client(handler),
        )
    )

    assert result.selected_coins == ["BTC", "ETH", "SOL"]
    assert result.l2books_scanned == 3
    assert "l2Book" in seen


def test_scan_markets_never_calls_exchange(tmp_path):
    settings = _settings(tmp_path)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        payload = _payload(request)
        if payload["type"] == "meta":
            return httpx.Response(200, json={"universe": [{"name": "BTC"}, {"name": "ETH"}]})
        if payload["type"] == "allMids":
            return httpx.Response(200, json={"BTC": "100", "ETH": "50"})
        return httpx.Response(200, json=_book(payload["coin"]))

    asyncio.run(
        run_scan_markets(
            MarketScanPlan(all_coins=True, max_coins=2, store=False, dry_run=False),
            settings,
            client=_mock_client(handler),
        )
    )

    assert paths
    assert set(paths) == {"/info"}


def test_market_metric_spread_depth_and_scannable():
    settings = load_settings()

    metric = build_market_metric("SOL", settings=settings, mid_price=25, orderbook=_book("SOL"))

    assert metric.coin == "SOL"
    assert metric.depth_usdc == 20000
    assert metric.spread_bps == 200
    assert metric.is_scannable is False


def test_scan_markets_stores_market_metrics(tmp_path):
    settings = _settings(tmp_path)
    settings.market_universe.max_spread_bps = 250
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _payload(request)
        if payload["type"] == "meta":
            return httpx.Response(200, json={"universe": [{"name": "BTC"}, {"name": "ETH"}]})
        if payload["type"] == "allMids":
            return httpx.Response(200, json={"BTC": "100", "ETH": "50"})
        return httpx.Response(200, json=_book(payload["coin"]))

    asyncio.run(
        run_scan_markets(
            MarketScanPlan(all_coins=True, max_coins=2, store=True, dry_run=False),
            settings,
            client=_mock_client(handler),
        )
    )

    with session_factory() as session:
        assert session.query(MarketMetric).count() == 2

