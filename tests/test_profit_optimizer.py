import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.optimization.profit_optimizer import StrategyConfig, run_strategy_tournament


def _write_rows(log_dir: Path, rows: list[dict]) -> None:
    log_dir.mkdir()
    with (log_dir / "simulation_decisions_append_only.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_optimizer_requires_costs_and_holdout_and_selects_robust_config(tmp_path: Path):
    log_dir = tmp_path / "logs"
    rows: list[dict] = []
    for index in range(30):
        rows.append(
            {
                "timestamp_ms": index,
                "bot_decision": "PAPER_OPEN_REPLAYED",
                "status": "LOCAL_REPLAY",
                "leader_action": "OPEN_LONG",
                "estimated_net_pnl_usdc": 0.1,
                "fee_cost_usdc": 0.01,
                "gross_pnl_usdc": 0.11,
                "edge_remaining_bps": 90,
                "signal_age_ms": 1_000,
                "copy_degradation_bps": 5,
                "consensus_wallets": 3,
                "copied_notional_usdt": 50,
            }
        )
    _write_rows(log_dir, rows)

    report = run_strategy_tournament(log_dir)

    assert report.best.validation_pnl_usdc > 0
    assert report.best.holdout_pnl_usdc > 0
    assert report.best.fees_usdc > 0
    assert report.no_trade_baseline_pnl_usdc == 0.0
    assert report.best.config.name != "no_trade_baseline"


def test_optimizer_rejects_overfit_train_only_config(tmp_path: Path):
    log_dir = tmp_path / "logs"
    rows: list[dict] = []
    for index in range(20):
        # Contiguous walk-forward split: first 60% train, next 20% validation, last 20% holdout.
        pnl = 1.0 if index < 12 else -2.0
        rows.append(
            {
                "bot_decision": "PAPER_OPEN_REPLAYED",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": pnl,
                "fee_cost_usdc": 0.01,
                "edge_remaining_bps": 100,
                "signal_age_ms": 1_000,
                "copy_degradation_bps": 5,
                "consensus_wallets": 3,
                "copied_notional_usdt": 50,
            }
        )
    _write_rows(log_dir, rows)

    report = run_strategy_tournament(log_dir)

    assert any(result.overfit_rejected for result in report.strategies if result.config.name != "no_trade_baseline")


def test_optimizer_does_not_use_holdout_to_select_best_config(tmp_path: Path):
    log_dir = tmp_path / "logs"
    rows: list[dict] = []
    for index in range(10):
        if index < 6:
            pnl = 1.0
        elif index < 8:
            pnl = 1.0
        else:
            pnl = -10.0
        rows.append(
            {
                "bot_decision": "PAPER_OPEN_REPLAYED",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": pnl,
                "fee_cost_usdc": 0.01,
                "edge_remaining_bps": 100,
                "signal_age_ms": 1_000,
                "copy_degradation_bps": 5,
                "consensus_wallets": 3,
                "copied_notional_usdt": 50,
            }
        )
    _write_rows(log_dir, rows)

    report = run_strategy_tournament(
        log_dir,
        configs=(
            StrategyConfig(name="no_trade_baseline", min_edge_remaining_bps=999_999),
            StrategyConfig(name="candidate", min_edge_remaining_bps=50),
        ),
    )

    assert report.best.config.name == "candidate"
    assert report.best.validation_pnl_usdc > 0
    assert report.best.holdout_pnl_usdc < 0
    assert report.best.holdout_failed_after_selection is True


def test_optimizer_never_counts_no_trade_rows_as_selected_trades(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_rows(
        log_dir,
        [
            {
                "bot_decision": "NO_TRADE",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": 99.0,
                "fee_cost_usdc": 0.0,
                "edge_remaining_bps": 100,
                "signal_age_ms": 1_000,
                "copy_degradation_bps": 5,
                "consensus_wallets": 3,
                "copied_notional_usdt": 50,
            }
        ],
    )

    report = run_strategy_tournament(
        log_dir,
        configs=(
            StrategyConfig(name="no_trade_baseline", min_edge_remaining_bps=999_999),
            StrategyConfig(name="candidate", min_edge_remaining_bps=50),
        ),
    )

    candidate = next(result for result in report.strategies if result.config.name == "candidate")
    assert candidate.selected_events == 0
    assert candidate.total_net_pnl_usdc == 0.0


def test_optimizer_uses_snapshot_ledger_when_latest_is_shadow_only(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_latest.jsonl").write_text(
        json.dumps(
            {
                "bot_decision": "EXTERNAL_GITHUB_PROFILE_EVALUATED",
                "paper_action_type": "ENGINE_EVALUATION",
                "status": "SIMULATION_ENGINE_EVENT",
                "coin": "SHADOW_PROFILE",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "paper_ledger": {
                    "closed_trade_stats": {
                        "recent_closed_trades": [
                            {
                                "observed_at_ms": 1,
                                "coin": "BTC",
                                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                                "paper_action_type": "CLOSE",
                                "status": "LOCAL_REPLAY",
                                "estimated_net_pnl_usdc": -0.6,
                                "gross_pnl_usdc": -0.5,
                                "fee_cost_usdc": 0.1,
                                "edge_remaining_bps": 100,
                                "signal_age_ms": 1_000,
                                "copy_degradation_bps": 5,
                                "consensus_wallets": 3,
                                "copied_notional_usdt": 50,
                                "dedupe_identity": "btc-close",
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    report = run_strategy_tournament(
        log_dir,
        configs=(
            StrategyConfig(name="no_trade_baseline", min_edge_remaining_bps=999_999),
            StrategyConfig(name="candidate", min_edge_remaining_bps=50),
        ),
    )
    candidate = next(result for result in report.strategies if result.config.name == "candidate")

    assert candidate.selected_events == 1
    assert candidate.total_net_pnl_usdc == -0.6
    assert report.protection_mode_recommended is True


def test_optimizer_cli_writes_reports(tmp_path: Path):
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "reports"
    _write_rows(
        log_dir,
        [
            {
                "bot_decision": "PAPER_OPEN_REPLAYED",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": 0.2,
                "fee_cost_usdc": 0.02,
                "edge_remaining_bps": 80,
                "signal_age_ms": 1_000,
                "copy_degradation_bps": 5,
                "consensus_wallets": 3,
                "copied_notional_usdt": 50,
            }
        ],
    )

    result = CliRunner().invoke(
        app,
        ["optimize-profit-config", "--from-logs", str(log_dir), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert "profit_optimization=simulation_only_no_fake_gain" in result.output
    assert "selection_uses_holdout=false" in result.output
    assert "protection_mode_recommended=" in result.output
    assert (output_dir / "strategy_tournament.json").exists()
    assert (output_dir / "best_profit_config.json").exists()
