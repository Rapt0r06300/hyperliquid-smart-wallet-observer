from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.metagraph.metagraph_export import export_metagraph_from_logs
from hl_observer.release.quality_gates import run_quality_gates


def _write_complete_logs(log_dir: Path) -> None:
    log_dir.mkdir(parents=True)
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp_ms": 10,
                        "wallet_address": "0x" + "a" * 40,
                        "coin": "ETH",
                        "bot_decision": "PAPER_ENTRY_REPLAYED",
                        "status": "LOCAL_REPLAY",
                        "estimated_net_pnl_usdc": 0.4,
                        "fee_cost_usdc": 0.01,
                        "execution": "forbidden",
                        "research_only": True,
                    }
                ),
                json.dumps(
                    {
                        "timestamp_ms": 20,
                        "wallet_address": "0x" + "b" * 40,
                        "coin": "BTC",
                        "bot_decision": "NO_TRADE",
                        "status": "REFUSED",
                        "reason": "EDGE_REMAINING_TOO_LOW",
                        "estimated_net_pnl_usdc": 0,
                        "execution": "forbidden",
                        "research_only": True,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "equity": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 1000.4,
                    "current_pnl_usdc": 0.4,
                    "realized_pnl_usdc": 0.4,
                    "unrealized_pnl_usdc": 0.0,
                    "open_exposure_usdt": 0.0,
                },
                "bot_simulation": {"ledger_events": [{"coin": "ETH"}]},
            }
        ),
        encoding="utf-8",
    )


def test_metagraph_export_writes_json_and_csv(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    output_dir = tmp_path / "reports"
    _write_complete_logs(log_dir)

    result = export_metagraph_from_logs(log_dir, output_dir=output_dir)

    assert result.points == 2
    assert result.final_pnl_usdc == 0.4
    assert result.json_path.exists()
    assert result.csv_path.exists()


def test_metagraph_export_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    output_dir = tmp_path / "reports"
    _write_complete_logs(log_dir)

    result = CliRunner().invoke(app, ["metagraph-export", "--from-logs", str(log_dir), "--output-dir", str(output_dir)])

    assert result.exit_code == 0
    assert "metagraph_export=local_simulation_only" in result.output
    assert "points=2" in result.output


def test_quality_gates_report_is_safe(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_complete_logs(log_dir)

    report = run_quality_gates(Path("."), log_dir=log_dir)

    gate_names = {gate.name for gate in report.gates}
    assert "GATE_SECURITY" in gate_names
    assert "GATE_RUNTIME_WRITES" in gate_names
    assert "GATE_DATA_QUALITY" in gate_names
    assert "GATE_REALTIME_RECOVERY" in gate_names
    assert "GATE_NO_REAL_EXECUTION" in gate_names
    assert report.hard_failed is False


def test_quality_gates_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_complete_logs(log_dir)

    result = CliRunner().invoke(app, ["quality-gates", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "quality_gates=simulation_read_only" in result.output
    assert "GATE_NO_REAL_EXECUTION" in result.output


def test_explain_decision_commands(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_complete_logs(log_dir)

    latest = CliRunner().invoke(app, ["explain-latest-decision-fr", "--from-logs", str(log_dir)])
    no_trade = CliRunner().invoke(app, ["explain-no-trade-fr", "--latest", "--from-logs", str(log_dir)])

    assert latest.exit_code == 0
    assert "simulation_only" in latest.output
    assert no_trade.exit_code == 0
    assert "EDGE_REMAINING_TOO_LOW" in no_trade.output
