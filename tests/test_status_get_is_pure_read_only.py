from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from hl_observer.config.settings import Settings
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _settings(tmp_path) -> Settings:
    return Settings(database_url=f"sqlite:///{(tmp_path / 'status.sqlite3').as_posix()}")


def test_status_get_100x_is_pure_and_network_free(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_DISABLE_ECONOMIC_WRITER", "1")
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 3.0
    state.simulation_equity_history = [
        {"timestamp_ms": 123, "current_equity_usdt": 1004.25, "current_pnl_usdc": 4.25}
    ]
    state.simulation_virtual_positions = {
        "leader|HYPE|SHORT": {
            "wallet_address": "0x" + "a" * 40,
            "coin": "HYPE",
            "direction": "SHORT",
            "size": 1.0,
            "avg_price": 70.0,
            "entry_costs": 0.0,
            "fee_already_embedded_in_entry_price": False,
            "source_delta_key": "pure-read-test",
        }
    }
    before = copy.deepcopy(state.__dict__)

    def _network_forbidden(*_a, **_k):
        raise AssertionError("GET /api/simulation/status must never perform network I/O")

    import hl_observer.ui.status_routes as status_routes
    monkeypatch.setattr(status_routes.httpx, "Client", _network_forbidden)

    app = create_ui_app(_settings(tmp_path), state=state)
    client = TestClient(app, raise_server_exceptions=True)
    for _ in range(100):
        payload = client.get("/api/simulation/status").json()
        assert payload["read_only"] is True
        assert payload["status_projection_pure"] is True
        assert payload["network_reads_from_status"] is False
        assert payload["equity_usdt"] == 1003.0
        assert payload["mark_to_market"]["read_status"] in {
            "LOCAL_BBO_MISSING", "NO_USABLE_MARK", "NO_SETTINGS", "NO_OPEN_POSITION"
        }
    assert state.__dict__ == before
