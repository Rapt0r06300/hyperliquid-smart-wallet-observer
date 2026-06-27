import re
from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.safe_actions import ALLOWED_ACTIONS
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_buttons.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_no_dead_buttons(tmp_path):
    html = _client(tmp_path).get("/").text
    actions = re.findall(r'data-action="([^"]+)"', html)

    assert actions
    assert all(action in ALLOWED_ACTIONS for action in actions)


def test_all_enabled_catalog_buttons_return_structured_result(tmp_path, monkeypatch):
    class FakeExplorerResult:
        full_addresses_found = 0
        transactions = []
        error_message = None

        def model_dump(self):
            return {
                "full_addresses_found": 0,
                "events_seen": 0,
                "transactions": [],
                "status": "IMPORT_REQUIRED",
            }

    async def fake_scrape_explorer(*args, **kwargs):
        return FakeExplorerResult()

    monkeypatch.setattr("hl_observer.ui.safe_actions.scrape_explorer", fake_scrape_explorer)
    client = _client(tmp_path)
    action_ids = [item["action_id"] for item in client.get("/api/actions/catalog").json() if item["enabled"]]

    for action_id in action_ids:
        response = client.post("/api/actions", json={"action": action_id})
        payload = response.json()
        assert response.status_code == 200
        assert payload["action_id"] == action_id
        assert "message" in payload
