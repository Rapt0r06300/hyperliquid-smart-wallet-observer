from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.schemas import UiActionResult
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_autoscan.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_autoscan_starts_discovery(tmp_path, monkeypatch):
    async def fake_action(action, settings, state):
        assert action == "autoscan_with_discovery"
        state.last_discovery_state = "completed"
        return UiActionResult(
            action=action,
            allowed=True,
            success=True,
            message="Recherche automatique terminee.",
            details={"discovery": {"candidates_found": 0}},
        )

    monkeypatch.setattr("hl_observer.ui.routes.run_safe_action", fake_action)
    response = _client(tmp_path).post("/api/autoscan/start")

    assert response.status_code == 200
    assert response.json()["action"] == "autoscan_with_discovery"


def test_autoscan_handles_no_discovery_candidates_clearly(tmp_path):
    response = _client(tmp_path).get("/api/simple-home")

    assert "Aucun wallet exploitable" in response.json()["discovery_empty_state"]


def test_autoscan_status_does_not_show_idle_after_started(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_autoscan_started.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.autoscan_started = True
    state.autoscan_current_step = "Resume pret"
    state.autoscan_progress_percent = 100
    client = TestClient(create_ui_app(settings, state))

    response = client.get("/api/autoscan/status")

    assert response.status_code == 200
    assert response.json()["state"] == "completed_no_wallets"


def test_simple_home_exposes_analysis_map_groups(tmp_path):
    payload = _client(tmp_path).get("/api/simple-home").json()

    groups = {group["group"] for group in payload["autoscan"]["analyzes"]}
    assert {"Marches", "Leaderboard", "Wallets", "Intelligence", "Paper/Risque"} <= groups


def test_ui_discovery_status_endpoint_exists(tmp_path):
    assert _client(tmp_path).get("/api/discovery/status").status_code == 200


def test_ui_discovery_candidates_endpoint_exists(tmp_path):
    assert _client(tmp_path).get("/api/discovery/candidates").status_code == 200


def test_ui_discovery_selected_endpoint_exists(tmp_path):
    assert _client(tmp_path).get("/api/discovery/selected").status_code == 200


def test_ui_no_fake_wallets_created(tmp_path):
    response = _client(tmp_path).get("/api/discovery/candidates")

    assert response.json() == []


def test_ui_discovery_events_are_french_simple_messages(tmp_path):
    with _client(tmp_path).websocket_connect("/ws") as ws:
        payload = ws.receive_json()

    assert "Connexion locale" in payload["message"]
