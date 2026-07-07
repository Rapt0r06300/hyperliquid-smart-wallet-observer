from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'loop_dashboard.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_loop_dashboard_route_exposes_latest_result_and_decision_trace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    memory_dir = tmp_path / "runtime" / "learning"
    memory_dir.mkdir(parents=True)
    (memory_dir / "latest_loop_result.json").write_text(
        json.dumps(
            {
                "run_id": "loop-route-test",
                "thesis": {"status": "READY", "source": "mainnet_readonly"},
                "learning": {"total_decisions": 1, "accepted_testnet": 0},
            }
        ),
        encoding="utf-8",
    )
    (memory_dir / "latest_loop_report.md").write_text(
        "# HyperSmart Loop Report\n\nTrace route test.\n",
        encoding="utf-8",
    )
    (memory_dir / "latest_decision_trace.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "sig-route-1",
                    "coin": "BTC",
                    "candidate_action": "open",
                    "decision_action": "ENTER",
                    "execution_status": "PREPARED_ONLY",
                }
            ]
        ),
        encoding="utf-8",
    )
    (memory_dir / "latest_loop_input_diagnostics.json").write_text(
        json.dumps({"status": "READY_CANDIDATES", "candidate_count": 1, "fills_seen": 1}),
        encoding="utf-8",
    )

    response = _client(tmp_path).get("/api/loop/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["has_latest_result"] is True
    assert payload["has_latest_trace"] is True
    assert payload["latest_result"]["run_id"] == "loop-route-test"
    assert payload["latest_decision_trace"][0]["candidate_id"] == "sig-route-1"
    assert payload["latest_input_diagnostics"]["status"] == "READY_CANDIDATES"
    assert "Trace route test" in payload["latest_report_preview"]


def test_simulation_page_reads_loop_dashboard_payload() -> None:
    html = Path("src/hl_observer/ui/static/simulation_v2.html").read_text(encoding="utf-8")

    assert "/api/loop/dashboard" in html
    assert "refreshLoopDashboard" in html
    assert "Boucle decision/testnet" in html
    assert "latest_decision_trace" in html
    assert "latest_input_diagnostics" in html
