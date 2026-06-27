from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.dashboard_truth.dashboard_truth_audit import run_dashboard_truth_audit


def _write_snapshot(log_dir: Path, *, placeholder: bool = False) -> None:
    log_dir.mkdir(parents=True)
    payload = {
        "equity": {
            "starting_equity_usdt": 1000.0,
            "current_equity_usdt": 1001.25,
            "current_pnl_usdc": 1.25,
            "realized_pnl_usdc": 0.5,
            "unrealized_pnl_usdc": 0.75,
            "open_exposure_usdt": 50.0,
        },
        "bot_simulation": {
            "ledger_events": [{"coin": "ETH", "status": "LOCAL_REPLAY"}],
        },
    }
    if placeholder:
        payload["equity"]["current_pnl_usdc"] = "TODO fake"
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_dashboard_truth_audit_accepts_metrics_with_provenance(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_snapshot(log_dir)

    audit = run_dashboard_truth_audit(log_dir)

    assert audit.ok is True
    assert audit.missing_metrics == ()
    assert any("current_pnl_usdc" in row for row in audit.provenance_rows)


def test_dashboard_truth_audit_rejects_placeholder(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_snapshot(log_dir, placeholder=True)

    audit = run_dashboard_truth_audit(log_dir)

    assert audit.ok is False
    assert audit.placeholder_findings


def test_dashboard_truth_audit_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_snapshot(log_dir)

    result = CliRunner().invoke(app, ["dashboard-truth-audit", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "dashboard_truth_audit=local_read_only" in result.output
    assert "ok=true" in result.output


def test_live_pnl_cli_reads_snapshot(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_snapshot(log_dir)
    (log_dir / "simulation_decisions_append_only.jsonl").write_text("", encoding="utf-8")

    result = CliRunner().invoke(app, ["live-pnl", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "live_pnl=local_simulation_only" in result.output
    assert "current_pnl_usdc=1.25" in result.output
    assert "closed_log_event_pnl_usdc=0.0" in result.output
    assert "pnl_scope=session_balance_is_fresh_launcher_state" in result.output
    assert "orders_created=0" in result.output
