from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_explorer.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_explorer_transactions_endpoint_exists(tmp_path):
    response = _client(tmp_path).get("/api/explorer/transactions")

    assert response.status_code == 200
    assert response.json() == []


def test_ui_live_data_endpoints_exist(tmp_path):
    client = _client(tmp_path)

    for path in [
        "/api/positions",
        "/api/fills/recent",
        "/api/position-deltas/recent",
        "/api/open-orders",
        "/api/wallets/top-by-coin",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert isinstance(response.json(), list)


def test_ui_shows_sources_attempted(tmp_path):
    response = _client(tmp_path).get("/api/simple-home")

    payload = response.json()
    assert "sources" in payload["simple_cards"]
    assert "explorer_status" in payload["simple_cards"]["sources"]


def test_ui_has_import_fallback(tmp_path):
    payload = _client(tmp_path).get("/api/simple-home").json()

    assert payload["simple_cards"]["sources"]["next_action"] in {
        "import_explorer_csv",
        "import_leaderboard_or_explorer",
        "scan_wallet_queue",
    }


def test_ui_mentions_explorer_transactions(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "Explorer / Transactions" in html
    assert "Sources essayees" in html


def test_ui_simple_view_shows_analyzed_data_panels(tmp_path):
    html = _client(tmp_path).get("/").text

    assert "Vue live des donnees analysees" in html
    assert "Positions reconstruites" in html
    assert "Fills recuperes" in html
    assert "Deltas de position" in html
