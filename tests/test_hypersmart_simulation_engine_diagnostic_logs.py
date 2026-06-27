from __future__ import annotations

import json

from pathlib import Path

from hyper_smart_observer.simulation import diagnostic_log
from hyper_smart_observer.simulation.diagnostic_log import write_simulation_engine_logs
from hyper_smart_observer.simulation.scenario_runner import run_conservative_scenario


def test_cli_simulation_engine_writes_logs_to_send(tmp_path) -> None:
    result = run_conservative_scenario(capital=1000.0)

    paths = write_simulation_engine_logs(result.engine, project_root=tmp_path, title="test_cli_simulation")

    logs_dir = tmp_path / "logs" / "logs à envoyer"
    assert logs_dir.exists()
    assert paths["directory"] == str(logs_dir)
    summary = logs_dir / "test_cli_simulation_resume_pour_chatgpt.md"
    decisions = logs_dir / "test_cli_simulation_decisions_latest.jsonl"
    snapshot = logs_dir / "test_cli_simulation_snapshot_latest.json"
    assert summary.exists()
    assert decisions.exists()
    assert snapshot.exists()
    assert not list(logs_dir.glob("*.sqlite3"))
    assert "Aucun /exchange" in summary.read_text(encoding="utf-8")

    rows = [json.loads(line) for line in decisions.read_text(encoding="utf-8").splitlines()]
    assert rows
    assert all(row["execution"] == "forbidden" for row in rows)
    assert {row["action"] for row in rows} == {"NO_TRADE"}
    assert rows[0]["reason"] == "EDGE_UNPROVEN_PROTECTION_MODE"


def test_cli_simulation_engine_falls_back_when_logs_to_send_is_unwritable(tmp_path, monkeypatch) -> None:
    result = run_conservative_scenario(capital=1000.0)
    primary = tmp_path / "logs" / "logs à envoyer"
    fallback = tmp_path / "hypersmart_logs_a_envoyer"

    def fake_probe(path: Path):
        if path == primary:
            return "PermissionError: locked"
        if path == fallback:
            path.mkdir(parents=True, exist_ok=True)
            return None
        return None

    monkeypatch.setattr(diagnostic_log, "_probe_log_dir", fake_probe)
    monkeypatch.setattr(diagnostic_log, "gettempdir", lambda: str(tmp_path))

    paths = write_simulation_engine_logs(result.engine, project_root=tmp_path, title="test_cli_simulation")

    assert paths["directory_status"] == "FALLBACK_USED"
    assert paths["directory"] == str(fallback)
    assert "primary_log_dir_unavailable" in paths["write_warnings"]
    assert Path(paths["decisions_jsonl"]).exists()
