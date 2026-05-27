from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def test_ui_websocket_connects(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_ws.sqlite3'}"
    init_db(settings.database_url)
    client = TestClient(create_ui_app(settings, UiState()))

    with client.websocket_connect("/ws") as websocket:
        event = websocket.receive_json()

    assert event["event_type"] == "heartbeat"
