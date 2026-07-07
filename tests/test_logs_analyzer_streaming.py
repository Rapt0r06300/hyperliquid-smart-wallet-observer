import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.simulation.log_metrics import analyze_logs_streaming, format_logs_analysis


def _write_rows(log_dir: Path, rows: list[dict]) -> None:
    log_dir.mkdir()
    with (log_dir / "simulation_decisions_append_only.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_logs_analyzer_streams_large_jsonl_and_counts_core_metrics(tmp_path: Path):
    log_dir = tmp_path / "logs"
    rows = [
        {
            "timestamp_ms": 1,
            "wallet_address": "0x" + "1" * 40,
            "coin": "BTC",
            "bot_decision": "PAPER_ENTRY_REPLAYED",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": -0.25,
            "gross_pnl_usdc": 0.1,
            "fee_cost_usdc": 0.35,
            "edge_remaining_bps": 12,
            "signal_age_ms": 5_000,
        },
        {
            "timestamp_ms": 2,
            "wallet_address": "0x" + "2" * 40,
            "coin": "ETH",
            "bot_decision": "NO_TRADE",
            "status": "REFUSED",
            "reason": "STALE_SIGNAL|EDGE_REMAINING_TOO_LOW",
            "edge_remaining_bps": -9999,
            "signal_age_ms": 40_000,
        },
        {
            "timestamp_ms": 3,
            "wallet_address": "0x" + "1" * 40,
            "coin": "BTC",
            "bot_decision": "NO_TRADE",
            "status": "REFUSED",
            "reason": "NO_MATCHING_PAPER_POSITION_FOR_CLOSE",
            "edge_remaining_bps": -9999,
        },
    ]
    _write_rows(log_dir, rows)

    report = analyze_logs_streaming(log_dir)
    text = format_logs_analysis(report)

    assert report.total_lines == 3
    assert report.total_decisions == 3
    assert report.accepted == 1
    assert report.refused == 2
    assert report.fees_usdc == 0.35
    assert report.pnl_by_coin["BTC"] == -0.25
    assert report.pnl_by_wallet["0x" + "1" * 40] == -0.25
    assert report.reasons["STALE_SIGNAL"] == 1
    assert report.reasons["EDGE_REMAINING_TOO_LOW"] == 1
    assert report.edge_sentinel_count == 2
    assert report.orphan_close_count == 1
    assert "fee_drag_ratio=" in text
    assert "execution=forbidden" in text


def test_logs_analyzer_cli_outputs_streaming_report(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_rows(log_dir, [{"bot_decision": "NO_TRADE", "status": "REFUSED", "reason": "STALE_SIGNAL"}])

    result = CliRunner().invoke(app, ["logs-analyze", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "logs_analyze=simulation_read_only" in result.output
    assert "STALE_SIGNAL" in result.output


def test_logs_analyzer_does_not_count_shadow_github_evaluations_as_accepted(tmp_path: Path):
    log_dir = tmp_path / "logs"
    rows = [
        {
            "bot_decision": "EXTERNAL_GITHUB_PROFILE_EVALUATED",
            "status": "SIMULATION_ENGINE_EVENT",
            "paper_action_type": "ENGINE_EVALUATION",
            "coin": "WHALE_WALLET_MIRROR",
            "copied_notional_usdt": 0.0,
            "estimated_net_pnl_usdc": 0.0,
        },
        {
            "bot_decision": "REJECT_NO_TRADE",
            "status": "REJECT_NO_TRADE",
            "reason": "EDGE_REMAINING_TOO_LOW",
            "coin": "HYPE",
        },
        {
            "bot_decision": "FUSION_PAPER_ENTRY",
            "status": "LOCAL_REPLAY",
            "coin": "BTC",
            "copied_notional_usdt": 40.0,
            "fee_cost_usdc": 0.02,
        },
    ]
    _write_rows(log_dir, rows)

    report = analyze_logs_streaming(log_dir)

    assert report.total_decisions == 3
    assert report.accepted == 1
    assert report.refused == 1
    assert report.actions["EXTERNAL_GITHUB_PROFILE_EVALUATED"] == 1
    assert report.reasons["EDGE_REMAINING_TOO_LOW"] == 1


def test_logs_analyzer_uses_snapshot_paper_ledger_when_latest_is_shadow_only(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    shadow_rows = [
        {
            "bot_decision": "EXTERNAL_GITHUB_PROFILE_EVALUATED",
            "bot_replay_action": "EXTERNAL_GITHUB_PROFILE_EVALUATED",
            "paper_action_type": "ENGINE_EVALUATION",
            "status": "SIMULATION_ENGINE_EVENT",
            "coin": "RESEARCH_PROFILE",
            "estimated_net_pnl_usdc": None,
            "fee_cost_usdc": 0.0,
            "delta_key": "shadow-profile-1",
        }
    ]
    (log_dir / "simulation_decisions_latest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in shadow_rows),
        encoding="utf-8",
    )
    close_rows = [
        {
            "observed_at_ms": 10,
            "wallet_address": "0x" + "1" * 40,
            "coin": "BTC",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "paper_action_type": "CLOSE",
            "status": "LOCAL_REPLAY",
            "reason": "SLTP_TAKE_PROFIT_LOCAL_REPLAY_NOT_AN_ORDER",
            "estimated_net_pnl_usdc": 1.25,
            "gross_pnl_usdc": 1.32,
            "fee_cost_usdc": 0.07,
            "dedupe_identity": "btc-close-1",
        },
        {
            "observed_at_ms": 20,
            "wallet_address": "0x" + "2" * 40,
            "coin": "ETH",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "paper_action_type": "CLOSE",
            "status": "LOCAL_REPLAY",
            "reason": "SLTP_STOP_LOSS_LOCAL_REPLAY_NOT_AN_ORDER",
            "estimated_net_pnl_usdc": -0.5,
            "gross_pnl_usdc": -0.44,
            "fee_cost_usdc": 0.06,
            "dedupe_identity": "eth-close-1",
        },
    ]
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {"ledger_events": shadow_rows},
                "paper_ledger": {"closed_trade_stats": {"recent_closed_trades": close_rows}},
            }
        ),
        encoding="utf-8",
    )

    report = analyze_logs_streaming(log_dir)

    assert {path.name for path in report.source_files} == {
        "simulation_decisions_latest.jsonl",
        "simulation_snapshot_latest.json",
    }
    assert report.total_decisions == 3
    assert report.accepted == 2
    assert report.positive_events == 1
    assert report.negative_events == 1
    assert report.net_pnl_usdc == 0.75
    assert report.fees_usdc == 0.13
    assert report.pnl_by_action["PAPER_CLOSE_REPLAYED"] == 0.75
    assert report.actions["EXTERNAL_GITHUB_PROFILE_EVALUATED"] == 1


def test_logs_analyzer_prefers_explicit_pnl_ledger_over_shadow_latest(tmp_path: Path):
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
    (log_dir / "simulation_pnl_ledger_latest.jsonl").write_text(
        json.dumps(
            {
                "observed_at_ms": 42,
                "wallet_address": "0x" + "3" * 40,
                "coin": "HYPE",
                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                "paper_action_type": "CLOSE",
                "status": "LOCAL_REPLAY",
                "reason": "SLTP_TAKE_PROFIT_LOCAL_REPLAY_NOT_AN_ORDER",
                "estimated_net_pnl_usdc": 0.8,
                "gross_pnl_usdc": 0.85,
                "fee_cost_usdc": 0.05,
                "dedupe_identity": "hype-close-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = analyze_logs_streaming(log_dir)

    assert [path.name for path in report.source_files] == ["simulation_pnl_ledger_latest.jsonl"]
    assert report.total_decisions == 1
    assert report.accepted == 1
    assert report.net_pnl_usdc == 0.8
    assert report.actions["EXTERNAL_GITHUB_PROFILE_EVALUATED"] == 0


def test_logs_analyzer_prefers_structured_dydx_log_and_event_level_pnl(tmp_path: Path):
    log_dir = tmp_path / "logs" / "logs à envoyer"
    structured_dir = tmp_path / "logs" / "structured"
    log_dir.mkdir(parents=True)
    structured_dir.mkdir(parents=True)
    (log_dir / "simulation_decisions_latest.jsonl").write_text("", encoding="utf-8")
    rows = [
        {
            "event_type": "PAPER_OPEN",
            "recorded_at_ms": 1,
            "market_id": "SOL-USD",
            "side": "LONG",
            "fee_paid": 0.04,
            "net_pnl_usdc": -0.04,
            "wallet_count": 4,
        },
        {
            "event_type": "NO_TRADE",
            "recorded_at_ms": 2,
            "reason": "STALE_SIGNAL",
            "net_pnl_usdc": -0.04,
        },
        {
            "event_type": "PAPER_PARTIAL_TP",
            "recorded_at_ms": 3,
            "market_id": "SOL-USD",
            "gross_pnl": 0.50,
            "net_pnl": 0.46,
            "net_pnl_usdc": 0.42,
            "reason": "TAKE_PROFIT_PARTIAL",
        },
    ]
    (structured_dir / "decisions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    report = analyze_logs_streaming(log_dir)

    assert [path.name for path in report.source_files] == ["decisions.jsonl"]
    assert report.total_decisions == 3
    assert report.accepted == 2
    assert report.refused == 1
    assert report.net_pnl_usdc == 0.42
    assert report.fees_usdc == 0.08
    assert report.reasons["STALE_SIGNAL"] == 1
    assert report.reasons["TAKE_PROFIT_PARTIAL"] == 0


def test_root_cause_and_refusal_cli_are_actionable(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_rows(
        log_dir,
        [
            {"bot_decision": "NO_TRADE", "status": "REFUSED", "reason": "STALE_SIGNAL", "edge_remaining_bps": -9999},
            {
                "bot_decision": "PAPER_ENTRY_REPLAYED",
                "status": "LOCAL_REPLAY",
                "estimated_net_pnl_usdc": -1,
                "fee_cost_usdc": 0.5,
                "gross_pnl_usdc": 0.0,
            },
        ],
    )

    root = CliRunner().invoke(app, ["root-cause-from-logs", "--from-logs", str(log_dir)])
    refusal = CliRunner().invoke(app, ["refusal-breakdown", "--from-logs", str(log_dir)])

    assert root.exit_code == 0
    assert "PNL_NET_NEGATIF_APRES_COUTS" in root.output
    assert "actions_correctives" in root.output
    assert refusal.exit_code == 0
    assert "top_refusal_reasons" in refusal.output
