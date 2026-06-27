from __future__ import annotations

import json

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.runtime import write_diagnostics
from hl_observer.runtime.write_diagnostics import (
    RUNTIME_WRITE_BLOCKED,
    RUNTIME_WRITE_OK,
    check_runtime_write_readiness,
    format_runtime_write_readiness,
)


def test_runtime_write_diagnostics_reports_ok_for_fresh_outputs(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        json.dumps({"bot_decision": "NO_TRADE", "execution": "forbidden"}) + "\n",
        encoding="utf-8",
    )

    report = check_runtime_write_readiness(log_dir, stale_after_seconds=3600)
    text = format_runtime_write_readiness(report)

    assert report.status == RUNTIME_WRITE_OK
    assert "orders_created=0" in text
    assert "processes_killed=0" in text


def test_runtime_write_diagnostics_reports_locked_target(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    target = log_dir / "realtime_replay_state.json"
    target.write_text("{}", encoding="utf-8")

    def fake_probe(path):
        if path.name == "realtime_replay_state.json":
            return False, "PermissionError: locked"
        return True, None

    monkeypatch.setattr(write_diagnostics, "_probe_existing_file_appendable", fake_probe)

    report = check_runtime_write_readiness(log_dir, stale_after_seconds=3600)

    assert report.status == RUNTIME_WRITE_BLOCKED
    assert "RUNTIME_OUTPUT_LOCKED_OR_NOT_WRITABLE" in report.reason
    assert report.blocked_targets[0].path.name == "realtime_replay_state.json"


def test_runtime_write_check_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_latest.jsonl").write_text(
        json.dumps({"bot_decision": "NO_TRADE"}) + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["runtime-write-check", "--from-logs", str(log_dir), "--stale-after-seconds", "3600"])

    assert result.exit_code == 0
    assert "runtime_write_check=local_simulation_outputs" in result.output
    assert "orders_created=0" in result.output
