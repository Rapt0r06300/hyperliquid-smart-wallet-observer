from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_v6.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_ui_mentions_leaderboard(tmp_path: Path):
    html = _client(tmp_path).get("/").text.lower()

    assert "leaderboard" in html


def test_ui_truncated_addresses_explained(tmp_path: Path):
    html = _client(tmp_path).get("/").text.lower()

    assert "tronque" in html
    assert "aucun wallet n'est invente" in html


def test_leaderboard_status_endpoint_exists(tmp_path: Path):
    response = _client(tmp_path).get("/api/leaderboard/status")

    assert response.status_code == 200
    assert "full_addresses_found" in response.json()
