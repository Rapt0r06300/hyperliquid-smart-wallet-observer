from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings
from hl_observer.markets.market_selector import select_markets_for_scan
from hl_observer.markets.universe import MarketUniverse, MarketUniverseItem
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def test_no_btc_only_hardcoded_scanner(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'no_btc_only.sqlite3'}"
    init_db(settings.database_url)

    assert len(settings.market_universe.default_fallback_coins) >= 4
    assert {"ETH", "SOL", "HYPE"}.issubset(set(settings.market_universe.default_fallback_coins))

    universe = MarketUniverse(
        items=[
            MarketUniverseItem(coin="BTC", source="test"),
            MarketUniverseItem(coin="ETH", source="test"),
            MarketUniverseItem(coin="SOL", source="test"),
            MarketUniverseItem(coin="HYPE", source="test"),
        ]
    )
    selection = select_markets_for_scan(universe, settings, max_coins=4)
    assert selection.coins != ["BTC"]
    assert {"ETH", "SOL", "HYPE"}.intersection(selection.coins)

    result = CliRunner().invoke(app, ["scan-markets", "--dry-run", "--all", "--max-coins", "4"])
    assert result.exit_code == 0, result.output
    assert "BTC, ETH, SOL, HYPE" in result.output

    html = TestClient(create_ui_app(settings, UiState())).get("/").text
    assert "Carnet BTC" not in html
    assert "Marches" in html

