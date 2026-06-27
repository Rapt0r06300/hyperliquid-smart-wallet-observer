from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_discovery.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_simple_home_includes_discovery_summary(tmp_path):
    response = _client(tmp_path).get("/api/simple-home")

    assert response.status_code == 200
    payload = response.json()
    assert "discovery" in payload["simple_cards"]
    assert "candidates_count" in payload["simple_cards"]["discovery"]


def test_ui_default_view_mentions_automatic_wallet_search(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "Recherche automatique des meilleurs wallets" in html


def test_ui_manual_wallet_input_is_secondary(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "Option secondaire" in html
    assert "Analyser une adresse précise" in html


def test_ui_positive_pnl_count_displayed(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "PnL" in html


def test_ui_positive_roi_count_displayed(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "ROI" in html


def test_ui_technical_discovery_details_only_in_expert(tmp_path):
    html = _client(tmp_path).get("/").text

    assert 'id="expertPanel"' in html
    assert "expert hidden" in html
    assert "Sources discovery" in html
