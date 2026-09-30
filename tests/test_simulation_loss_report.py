from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.simulation.decision_replay_analyzer import analyze_decision_logs
from hl_observer.simulation.loss_attribution import build_loss_attribution_report


def _write_events(log_dir: Path) -> None:
    log_dir.mkdir(parents=True)
    rows = [
        {
            "timestamp_ms": 1000,
            "wallet_address": "0x" + "1" * 40,
            "coin": "ETH",
            "leader_action": "OPEN_LONG",
            "leader_side": "LONG",
            "bot_decision": "PAPER_ENTRY_REPLAYED",
            "status": "LOCAL_REPLAY",
            "reason": "LOCAL_REPLAY_ONLY_EDGE_GATE_REQUIRED_FOR_REAL_PAPER_INTENT",
            "edge_remaining_bps": 28.0,
            "copy_degradation_bps": 35.0,
            "signal_age_ms": 25_000,
            "estimated_net_pnl_usdc": -0.25,
            "fee_cost_usdc": 0.08,
            "execution": "forbidden",
            "research_only": True,
        },
        {
            "timestamp_ms": 1200,
            "wallet_address": "0x" + "2" * 40,
            "coin": "BTC",
            "bot_decision": "REJECT_NO_TRADE",
            "status": "REFUSED",
            "reason": "EDGE_REMAINING_TOO_LOW",
            "estimated_net_pnl_usdc": 0,
            "fee_cost_usdc": 0,
            "execution": "forbidden",
            "research_only": True,
        },
    ]
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_loss_report_detects_root_causes(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    report = build_loss_attribution_report(log_dir)

    assert report.analysis.event_count == 2
    assert report.analysis.refused_count == 1
    assert "FEES_DRAG" in report.root_causes.causes
    assert "COPY_DEGRADATION_TOO_HIGH" in report.root_causes.causes
    assert "LATE_ENTRY" in report.root_causes.causes


def test_decision_log_analysis_aggregates_pnl_by_coin(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    analysis = analyze_decision_logs(log_dir)

    assert analysis.pnl_by_coin["ETH"] == -0.25
    assert analysis.top_refusal_reasons == (("EDGE_REMAINING_TOO_LOW", 1),)


def test_simulation_loss_report_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    result = CliRunner().invoke(app, ["simulation-loss-report", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "simulation_log_analysis=local_read_only" in result.output
    assert "EDGE_MODEL_TOO_OPTIMISTIC" in result.output
    assert "security=simulation_only_no_real_order" in result.output


def test_explain_loss_fr_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    result = CliRunner().invoke(app, ["explain-loss-fr", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "explain_loss_fr=simulation_only" in result.output
    assert "frais" in result.output.lower() or "edge" in result.output.lower()
