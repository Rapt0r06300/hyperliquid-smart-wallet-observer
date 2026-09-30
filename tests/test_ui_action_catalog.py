from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.safe_actions import ALLOWED_ACTIONS
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_actions.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_action_catalog_endpoint_exists(tmp_path: Path):
    response = _client(tmp_path).get("/api/actions/catalog")

    assert response.status_code == 200
    assert response.json()


def test_all_enabled_buttons_have_safe_action(tmp_path: Path):
    items = _client(tmp_path).get("/api/actions/catalog").json()

    assert all(item["action_id"] in ALLOWED_ACTIONS for item in items if item["enabled"])


def test_expert_buttons_grouped_by_mission(tmp_path: Path):
    items = _client(tmp_path).get("/api/actions/catalog").json()

    assert {item["group"] for item in items} >= {"Verifier", "Sources", "Rechercher"}
