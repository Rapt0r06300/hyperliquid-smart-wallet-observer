from __future__ import annotations

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings
from hl_observer.markets.universe import build_market_universe


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

