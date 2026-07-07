import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.calibration.ledger_pnl_calibration import (
    build_ledger_pnl_calibration_report,
    format_ledger_pnl_calibration_report,
)
from hl_observer.cli import app


def _write_pnl_rows(log_dir: Path, rows: list[dict]) -> None:
    log_dir.mkdir(parents=True)
    (log_dir / "simulation_pnl_ledger_latest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_ledger_pnl_calibration_recommends_replay_flags_from_real_losses(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_pnl_rows(
        log_dir,
        [
            {
                "timestamp_ms": 1,
                "wallet_address": "0x" + "1" * 40,
                "coin": "BTC",
                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                "paper_action_type": "CLOSE",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": -0.80,
                "gross_pnl_usdc": -0.50,
                "fee_cost_usdc": 0.30,
                "edge_remaining_bps": 8,
                "signal_age_ms": 8_000,
                "consensus_wallets": 1,
            },
            {
                "timestamp_ms": 2,
                "wallet_address": "0x" + "2" * 40,
                "coin": "ETH",
                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                "paper_action_type": "CLOSE",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": 0.20,
                "gross_pnl_usdc": 0.25,
                "fee_cost_usdc": 0.05,
                "edge_remaining_bps": 30,
                "signal_age_ms": 1_000,
                "consensus_wallets": 3,
            },
            {
                "timestamp_ms": 3,
                "wallet_address": "0x" + "3" * 40,
                "coin": "BTC",
                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                "paper_action_type": "CLOSE",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": -0.20,
                "gross_pnl_usdc": -0.16,
                "fee_cost_usdc": 0.04,
                "edge_remaining_bps": 10,
                "signal_age_ms": 7_000,
                "consensus_wallets": 1,
            },
            {
                "timestamp_ms": 4,
                "wallet_address": "0x" + "4" * 40,
                "coin": "SOL",
                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                "paper_action_type": "CLOSE",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": -0.10,
                "gross_pnl_usdc": -0.08,
                "fee_cost_usdc": 0.02,
                "edge_remaining_bps": 12,
                "signal_age_ms": 6_000,
                "consensus_wallets": 1,
            },
            {
                "timestamp_ms": 5,
                "coin": "BTC",
                "bot_replay_action": "NO_TRADE",
                "status": "REFUSED",
                "reason": "STALE_SIGNAL",
            },
        ],
    )

    report = build_ledger_pnl_calibration_report(log_dir)
    text = format_ledger_pnl_calibration_report(report)
    flags = {item.name: item.proposed_value for item in report.flag_candidates}

    assert report.source_files == ("simulation_pnl_ledger_latest.jsonl",)
    assert report.net_pnl_usdc == -0.9
    assert flags["HYPERSMART_REQUIRE_PROFIT_FACTOR_REPLAY_GATE"] == "true"
    assert flags["HYPERSMART_MIN_PAPER_NOTIONAL_USDT"] == "40"
    assert flags["HYPERSMART_MIN_CONSENSUS_WALLETS"] == "3"
    assert "BTC" in flags["HYPERSMART_REPLAY_COIN_COOLDOWN_SET"]
    assert "replay_ab_required=true" in text
    assert "profit_guarantee=false" in text


def test_ledger_pnl_calibration_reports_open_exposure_risk(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_pnl_rows(log_dir, [])
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "open_positions": [{"coin": f"C{i}"} for i in range(12)],
                    "open_exposure_usdt": 480.0,
                    "unrealized_pnl_usdc": -1.25,
                }
            }
        ),
        encoding="utf-8",
    )

    report = build_ledger_pnl_calibration_report(log_dir)
    flags = {item.name: item.proposed_value for item in report.flag_candidates}
    text = format_ledger_pnl_calibration_report(report)

    assert report.open_positions_count == 12
    assert report.open_exposure_usdt == 480.0
    assert report.unrealized_pnl_usdc == -1.25
    assert flags["HYPERSMART_MAX_OPEN_PAPER_POSITIONS"] == "5"
    assert flags["HYPERSMART_UNREALIZED_DRAWDOWN_GUARD_USDT"] == "1.0"
    assert "open_positions_count=12" in text
    assert "Le latent ouvert est negatif" in text


def test_ledger_pnl_calibration_cli_outputs_research_only(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_pnl_rows(log_dir, [])

    result = CliRunner().invoke(app, ["ledger-pnl-calibration", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "ledger_pnl_calibration=research_only" in result.output
    assert "paper_simulation_only=true" in result.output
