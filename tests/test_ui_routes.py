from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_routes.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_ui_routes_do_not_require_private_key(tmp_path, monkeypatch):
    monkeypatch.delenv("HL_TESTNET_PRIVATE_KEY", raising=False)
    client = _client(tmp_path)

    assert client.get("/api/status").status_code == 200
    assert client.get("/api/wallets").status_code == 200
    assert client.get("/api/signals").status_code == 200
    assert client.get("/api/paper").status_code == 200


def test_ui_action_endpoint_runs_doctor(tmp_path):
    client = _client(tmp_path)

    response = client.post("/api/actions", json={"action": "doctor"})

    assert response.status_code == 200
    assert response.json()["success"] is True
