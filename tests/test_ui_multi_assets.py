from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_multi_assets.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_ui_simple_home_mentions_altcoins(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "altcoins" in html.lower()
    assert "Le logiciel ne regarde pas seulement BTC" in html


def test_ui_markets_card_replaces_btc_only_card(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "Marches" in html
    assert "Carnet BTC" not in html


def test_ui_top_wallets_by_coin_endpoint_exists(tmp_path):
    response = _client(tmp_path).get("/api/wallets/top-by-coin")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_ui_market_opportunities_endpoint_exists(tmp_path):
    response = _client(tmp_path).get("/api/markets/opportunities")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_ui_expert_shows_coin_metrics(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "Metriques coins" in html
    assert 'id="coinMetrics"' in html

