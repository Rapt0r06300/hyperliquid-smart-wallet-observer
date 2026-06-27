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
