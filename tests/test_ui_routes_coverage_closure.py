from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.simulation_log_export import LOGS_TO_SEND_DIRNAME
from hl_observer.ui.state import UiState


def _huge_db_client(
    tmp_path: Path,
    monkeypatch,
    *,
    snapshot_text: str | None,
    state: UiState | None = None,
) -> tuple[TestClient, Path]:
    settings = load_settings()
    db_path = tmp_path / "data" / "routes_coverage.sqlite3"
    settings.database_url = f"sqlite:///{db_path}"
    settings.logs_dir = str(tmp_path / "logs")
    init_db(settings.database_url)
    with db_path.open("ab") as handle:
        handle.write(b"0" * (2 * 1024 * 1024))

    logs_to_send = Path(settings.logs_dir) / LOGS_TO_SEND_DIRNAME
    logs_to_send.mkdir(parents=True, exist_ok=True)
    snapshot_path = logs_to_send / "simulation_snapshot_latest.json"
    if snapshot_text is not None:
        snapshot_path.write_text(snapshot_text, encoding="utf-8")

    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_SNAPSHOT", "1")
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_DB_THRESHOLD_MB", "1")
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_SNAPSHOT_MAX_AGE_MS", "60000")
    return TestClient(create_ui_app(settings, state or UiState())), snapshot_path


def test_overview_invalid_snapshot_json_fails_closed_to_live_paper_state(tmp_path: Path, monkeypatch):
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 1.25
    state.simulation_equity_history = [{"current_equity_usdt": 1001.25}]

    client, _snapshot_path = _huge_db_client(
        tmp_path,
        monkeypatch,
        snapshot_text="{not-json",
        state=state,
    )
    payload = client.get("/api/simulation/overview?limit=3").json()

    assert payload["overview_fast_state"] is True
    assert payload["overview_fast_snapshot"] is False
    assert payload["read_only"] is True
    assert payload["paper_mock_usdc_only"] is True
    assert payload["equity"]["current_equity_usdt"] == 1001.25


def test_overview_non_mapping_snapshot_fails_closed_to_live_paper_state(tmp_path: Path, monkeypatch):
    client, _snapshot_path = _huge_db_client(
        tmp_path,
        monkeypatch,
        snapshot_text=json.dumps([{"bot_simulation": {}}]),
    )

    payload = client.get("/api/simulation/overview?limit=2").json()

    assert payload["overview_fast_state"] is True
    assert payload["overview_fast_snapshot"] is False
    assert payload["bot_simulation"]["source"] == "LIVE_UI_STATE_FAST_OVERVIEW"
    assert payload["bot_simulation"]["no_fake_pnl"] is True


def test_overview_snapshot_without_paper_payload_is_rejected(tmp_path: Path, monkeypatch):
    client, _snapshot_path = _huge_db_client(
        tmp_path,
        monkeypatch,
        snapshot_text=json.dumps({"mode": "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA"}),
    )

    payload = client.get("/api/simulation/overview?limit=2").json()

    assert payload["overview_fast_state"] is True
    assert payload["overview_fast_snapshot"] is False
    assert payload["read_only"] is True


def test_overview_live_state_reconstructs_open_exposure_from_position(tmp_path: Path, monkeypatch):
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_virtual_positions = {
        "paper-1": {
            "coin": "HYPE",
            "side": "LONG",
            "size": "2",
            "entry_price": "40",
        }
    }
    state.simulation_equity_history = [
        {
            "current_equity_usdt": 1000.0,
            "current_pnl_usdc": 0.0,
            "open_exposure_usdt": 0.0,
        }
    ]

    client, snapshot_path = _huge_db_client(
        tmp_path,
        monkeypatch,
        snapshot_text=None,
        state=state,
    )
    payload = client.get("/api/simulation/overview?limit=5").json()

    assert payload["overview_fast_state"] is True
    assert payload["equity"]["open_exposure_usdt"] == 80.0
    assert payload["bot_simulation"]["open_exposure_usdt"] == 80.0
    assert payload["bot_simulation"]["open_local_positions"] == 1
    assert snapshot_path.exists()


def test_overview_snapshot_defaults_preserve_read_only_contract(tmp_path: Path, monkeypatch):
    snapshot = {
        "bot_simulation": {
            "events": [{"id": 1}, {"id": 2}],
            "open_positions": [{"coin": "BTC"}],
        }
    }
    client, _snapshot_path = _huge_db_client(
        tmp_path,
        monkeypatch,
        snapshot_text=json.dumps(snapshot),
    )

    payload = client.get("/api/simulation/overview?limit=1").json()

    assert payload["overview_fast_snapshot"] is True
    assert payload["overview_cache_hit"] is False
    assert payload["read_only"] is True
    assert payload["paper_mock_usdc_only"] is True
    assert payload["mode"] == "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA"
    assert len(payload["bot_simulation"]["events"]) == 1
    assert payload["message"].startswith("Snapshot runtime compact")
