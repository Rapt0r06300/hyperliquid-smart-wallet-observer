import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.optimization.closed_ledger_replay import (
    ClosedLedgerReplayConfig,
    run_closed_ledger_replay,
)


def _write_snapshot(log_dir: Path, rows: list[dict]) -> None:
    log_dir.mkdir()
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps({"paper_ledger": {"closed_trade_stats": {"recent_closed_trades": rows}}}),
        encoding="utf-8",
    )


def _close_row(index: int, coin: str, pnl: float, *, notional: float = 50.0, entry_context: bool = True) -> dict:
    return {
        "observed_at_ms": 1_800_000_000_000 + index,
        "coin": coin,
        "leader_side": "LONG",
        "paper_action_type": "CLOSE",
        "bot_replay_action": "PAPER_CLOSE_REPLAYED",
        "status": "LOCAL_REPLAY",
        "estimated_net_pnl_usdc": pnl,
        "gross_pnl_usdc": pnl + 0.02,
        "fee_cost_usdc": 0.02,
        "copied_notional_usdt": notional,
        "entry_context_found": entry_context,
        "dedupe_identity": f"{coin}-{index}",
    }


def test_closed_ledger_replay_cooldown_is_causal_and_keeps_first_loss(tmp_path: Path):
    log_dir = tmp_path / "logs"
    rows = [
        _close_row(0, "BTC", -1.0),
        _close_row(1, "BTC", -1.0),
        _close_row(2, "ETH", 2.0),
        _close_row(3, "BTC", -1.0),
        _close_row(4, "BTC", -1.0),
        _close_row(5, "ETH", 2.0),
        _close_row(6, "ETH", 2.0),
        _close_row(7, "BTC", -1.0),
        _close_row(8, "ETH", 2.0),
        _close_row(9, "BTC", -1.0),
    ]
    _write_snapshot(log_dir, rows)

    report = run_closed_ledger_replay(
        log_dir,
        configs=(
            ClosedLedgerReplayConfig(name="all"),
            ClosedLedgerReplayConfig(name="cooldown1", cooldown_after_loss_events=1),
        ),
    )

    all_result = next(result for result in report.strategies if result.config.name == "all")
    cooldown = next(result for result in report.strategies if result.config.name == "cooldown1")

    assert all_result.selected_closed_trades == 10
    assert cooldown.selected_closed_trades == 7
    assert cooldown.skipped_by_cooldown == 3
    assert cooldown.total_net_pnl_usdc > all_result.total_net_pnl_usdc
    assert cooldown.losing_trades == 3


def test_closed_ledger_replay_prefers_no_trade_when_closed_trades_lose(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_snapshot(log_dir, [_close_row(index, "BTC", -0.5) for index in range(8)])

    report = run_closed_ledger_replay(log_dir)

    assert report.best.config.name == "no_trade_baseline"
    assert report.protection_mode_recommended is True


def test_closed_ledger_replay_cli_writes_reports(tmp_path: Path):
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "reports"
    _write_snapshot(log_dir, [_close_row(0, "HYPE", 0.25), _close_row(1, "HYPE", -0.1)])

    result = CliRunner().invoke(
        app,
        ["closed-ledger-replay", "--from-logs", str(log_dir), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert "closed_ledger_replay=simulation_only_no_fake_gain" in result.output
    assert "selection_uses_holdout=false" in result.output
    assert "profit_guarantee=false" in result.output
    assert (output_dir / "closed_ledger_replay.json").exists()
    assert (output_dir / "closed_ledger_replay_summary.md").exists()
