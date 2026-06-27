import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.simulation.tuning_report import build_simulation_tuning_report, format_simulation_tuning_report


def test_simulation_tuning_report_recommends_cooldowns_and_stricter_consensus(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    rows = [
        {
            "timestamp_ms": 1_000,
            "wallet_address": "0x" + "a" * 40,
            "coin": "BTC",
            "leader_action": "OPEN_LONG",
            "bot_decision": "PAPER_ENTRY_REPLAYED",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": -0.7,
            "fee_cost_usdc": 0.1,
            "signal_age_ms": 7_000,
            "copy_degradation_bps": 30,
            "research_only": True,
        },
        {
            "timestamp_ms": 2_000,
            "wallet_address": "0x" + "b" * 40,
            "coin": "ETH",
            "leader_action": "OPEN_LONG",
            "bot_decision": "PAPER_ENTRY_REPLAYED",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": 0.3,
            "fee_cost_usdc": 0.02,
            "signal_age_ms": 500,
            "copy_degradation_bps": 12,
            "research_only": True,
        },
        {
            "timestamp_ms": 3_000,
            "wallet_address": "0x" + "c" * 40,
            "coin": "BTC",
            "leader_action": "OPEN_LONG",
            "bot_decision": "NO_TRADE",
            "status": "REFUSED",
            "reason": "STALE_SIGNAL",
            "signal_age_ms": 8_000,
            "research_only": True,
        },
    ]
    with (log_dir / "simulation_decisions_latest.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    report = build_simulation_tuning_report(log_dir)
    text = format_simulation_tuning_report(report)

    assert report.recommended_min_consensus_wallets == 3
    assert "BTC" in report.recommended_blocked_coins
    assert "ETH" in report.recommended_watch_coins
    assert report.recommended_max_signal_age_ms == 3_000
    assert "profit_guarantee=false" in text
    assert "execution=forbidden" in text


def test_simulation_tuning_report_cli_outputs_research_only(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_latest.jsonl").write_text("", encoding="utf-8")

    result = CliRunner().invoke(app, ["simulation-tuning-report", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "simulation_tuning_report=research_only" in result.output
    assert "paper_simulation_only=true" in result.output
