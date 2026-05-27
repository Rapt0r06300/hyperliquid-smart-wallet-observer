from __future__ import annotations

from hl_observer.config.loader import load_settings
from hl_observer.markets.market_selector import select_markets_for_scan
from hl_observer.markets.universe import MarketUniverse, MarketUniverseItem


def _universe() -> MarketUniverse:
    return MarketUniverse(
        items=[
            MarketUniverseItem(coin="BTC", source="test"),
            MarketUniverseItem(coin="ETH", source="test"),
            MarketUniverseItem(coin="SOL", source="test"),
            MarketUniverseItem(coin="HYPE", source="test"),
        ],
        sources_used=["test"],
    )


def test_market_selector_does_not_return_only_btc():
    settings = load_settings()

    selected = select_markets_for_scan(_universe(), settings, max_coins=4)

    assert selected.coins != ["BTC"]
    assert {"ETH", "SOL", "HYPE"}.intersection(selected.coins)


def test_market_selector_respects_max_coins():
    settings = load_settings()

    selected = select_markets_for_scan(_universe(), settings, max_coins=2)

    assert len(selected.coins) == 2


def test_market_selector_excludes_configured_coins():
    settings = load_settings()
    settings.market_universe.excluded_coins = ["SOL"]

    selected = select_markets_for_scan(_universe(), settings, max_coins=4)

    assert "SOL" not in selected.coins
    assert selected.rejected["SOL"] == "configured_exclusion"

