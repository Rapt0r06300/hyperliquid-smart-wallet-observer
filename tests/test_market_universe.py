from __future__ import annotations

import asyncio

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings
from hl_observer.markets.scanner import MarketDiscoveryPlan, run_discover_markets
from hl_observer.markets.universe import build_market_universe
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketSnapshot, RawEvent


def test_discover_markets_command_exists():
    result = CliRunner().invoke(app, ["discover-markets", "--help"])

    assert result.exit_code == 0
    assert "Discover Hyperliquid markets" in result.output


def test_market_universe_from_meta_includes_altcoins():
    settings = load_settings()
    universe = build_market_universe(
        settings,
        meta_payload={
            "universe": [
                {"name": "BTC"},
                {"name": "ETH"},
                {"name": "SOL"},
                {"name": "HYPE"},
                {"name": "DOGE"},
            ]
        },
    )

    assert {"BTC", "ETH", "SOL", "HYPE", "DOGE"}.issubset(set(universe.coins))
    assert universe.altcoins_count >= 3


def test_market_universe_fallback_from_all_mids():
    settings = load_settings()
    universe = build_market_universe(settings, all_mids_payload={"BTC": "100", "SOL": "10", "HYPE": "5"})

    assert universe.coins == ["BTC", "SOL", "HYPE"]
    assert universe.items[1].mid_price == 10.0


def test_default_config_altcoins_enabled():
    settings = load_settings()

    assert settings.market_universe.altcoins_enabled is True
    assert len(settings.market_universe.default_fallback_coins) >= 4
    assert "SOL" in settings.market_universe.default_fallback_coins


def test_discover_markets_store_writes_all_mids_market_snapshot(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'markets.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))

    class FakeInfoClient:
        async def meta(self):
            return {"universe": [{"name": "BTC"}, {"name": "HYPE"}]}

        async def all_mids(self):
            return {"BTC": "65000", "HYPE": "25"}

    result = asyncio.run(
        run_discover_markets(
            MarketDiscoveryPlan(store=True, dry_run=False, max_coins=2),
            settings,
            client=FakeInfoClient(),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        raw_all_mids = session.query(RawEvent).filter(RawEvent.request_type == "allMids").one()
        snapshot = session.query(MarketSnapshot).one()

    assert result.stored is True
    assert raw_all_mids.response_payload_json["HYPE"] == "25"
    assert snapshot.source == "allMids"
    assert snapshot.raw_json["BTC"] == "65000"
