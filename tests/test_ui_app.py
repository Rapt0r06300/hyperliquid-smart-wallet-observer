from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hl_observer.cli import app as cli_app
from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def _button_labels(html: str) -> list[str]:
    return re.findall(r"<button[^>]*>(.*?)</button>", html, flags=re.IGNORECASE | re.DOTALL)


def test_ui_status_endpoint(tmp_path):
    client = _client(tmp_path)

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app_name"] == "Hyperliquid Smart-Wallet Observer"
    assert payload["mainnet_enabled"] is False
    assert "raw_events" in payload["counts"]


def test_ui_index_served(tmp_path):
    client = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "Command Center" in response.text


def test_ui_static_assets_served(tmp_path):
    client = _client(tmp_path)

    css = client.get("/static/app.css")
    js = client.get("/static/app.js")

    assert css.status_code == 200
    assert "#05070d" in css.text
    assert js.status_code == 200
    assert "WebSocket" in js.text


def test_ui_has_no_live_button(tmp_path):
    html = _client(tmp_path).get("/").text

    assert all("live" not in label.lower() for label in _button_labels(html))


def test_ui_has_no_withdraw_button(tmp_path):
    html = _client(tmp_path).get("/").text

    assert all("withdraw" not in label.lower() for label in _button_labels(html))


def test_ui_has_no_mainnet_button(tmp_path):
    html = _client(tmp_path).get("/").text

    assert all("mainnet" not in label.lower() for label in _button_labels(html))


def test_ui_refuses_public_bind_host():
    result = CliRunner().invoke(cli_app, ["ui", "--host", "0.0.0.0"])

    assert result.exit_code == 1
    assert "Refusing to expose" in result.output
