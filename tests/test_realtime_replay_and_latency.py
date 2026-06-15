from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.realtime.latency_report import build_latency_report
from hl_observer.realtime.replay import replay_events_from_logs
from hl_observer.simulation.decision_replay_analyzer import (
    analyze_decision_logs_summary,
    load_recent_decision_events,
)


def _write_events(log_dir: Path) -> None:
    log_dir.mkdir(parents=True)
    rows = [
        {
            "timestamp_ms": 100,
            "wallet_address": "0x" + "a" * 40,
            "coin": "ETH",
            "bot_decision": "PAPER_ENTRY_REPLAYED",
            "status": "LOCAL_REPLAY",
            "signal_age_ms": 100,
            "estimated_net_pnl_usdc": 0.1,
            "execution": "forbidden",
            "research_only": True,
        },
        {
            "timestamp_ms": 200,
            "wallet_address": "0x" + "b" * 40,
            "coin": "BTC",
            "bot_decision": "NO_TRADE",
            "status": "REFUSED",
            "reason": "STALE_SIGNAL",
            "signal_age_ms": 4500,
            "estimated_net_pnl_usdc": 0,
            "execution": "forbidden",
            "research_only": True,
        },
    ]
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_realtime_replay_writes_local_replay_files(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    result = replay_events_from_logs(log_dir, speed="5x", limit=1)

    assert result.events_available == 2
    assert result.events_replayed == 1
    assert result.output_path.exists()
    assert result.state_path.exists()
    assert "forbidden" in result.output_path.read_text(encoding="utf-8")


def test_realtime_replay_reports_locked_output_without_crashing(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    from hl_observer.realtime import replay as replay_module

    def fail_write(_path, _text):
        return "locked"

    monkeypatch.setattr(replay_module, "_safe_write_text", fail_write)

    result = replay_module.replay_events_from_logs(log_dir, limit=1)

    assert result.events_replayed == 1
    assert result.write_warnings == ("locked", "locked")


def test_recent_decision_loader_reads_tail_without_loading_every_event(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir(parents=True)
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "timestamp_ms": index,
                    "coin": f"COIN{index}",
                    "bot_decision": "NO_TRADE" if index % 2 else "PAPER_ENTRY_REPLAYED",
                    "status": "REFUSED" if index % 2 else "LOCAL_REPLAY",
                    "estimated_net_pnl_usdc": index / 100,
                    "execution": "forbidden",
                    "research_only": True,
                }
            )
            + "\n"
            for index in range(20)
        ),
        encoding="utf-8",
    )

    events = load_recent_decision_events(log_dir, limit=3)

    assert [event.coin for event in events] == ["COIN17", "COIN18", "COIN19"]


def test_summary_cache_is_reused_only_for_same_source_signature(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    first = analyze_decision_logs_summary(log_dir)
    second = analyze_decision_logs_summary(log_dir)

    assert first.event_count == 2
    assert second.event_count == 2
    assert (log_dir / "simulation_log_summary_cache.json").exists()

    with (log_dir / "simulation_decisions_append_only.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp_ms": 300, "coin": "SOL", "bot_decision": "NO_TRADE"}) + "\n")

    refreshed = analyze_decision_logs_summary(log_dir)

    assert refreshed.event_count == 3


def test_summary_uses_structured_dydx_log_when_latest_export_is_empty(tmp_path):
    log_dir = tmp_path / "logs" / "logs à envoyer"
    structured_dir = tmp_path / "logs" / "structured"
    log_dir.mkdir(parents=True)
    structured_dir.mkdir(parents=True)
    (log_dir / "simulation_decisions_latest.jsonl").write_text("", encoding="utf-8")
    rows = [
        {
            "event_type": "NO_TRADE",
            "recorded_at_ms": 10,
            "reason": "EDGE_INSUFFICIENT",
            "net_pnl_usdc": 0.0,
            "equity_usdc": 1000.0,
        },
        {
            "event_type": "PAPER_OPEN",
            "recorded_at_ms": 20,
            "market_id": "BTC-USD",
            "side": "LONG",
            "fee_paid": 0.05,
            "net_pnl_usdc": -0.05,
            "equity_usdc": 999.95,
            "wallet_count": 3,
        },
        {
            "event_type": "NO_TRADE",
            "recorded_at_ms": 30,
            "reason": "STALE_SIGNAL",
            "net_pnl_usdc": -0.05,
            "equity_usdc": 999.95,
        },
        {
            "event_type": "PAPER_CLOSE",
            "recorded_at_ms": 40,
            "market_id": "BTC-USD",
            "side": "LONG",
            "gross_pnl": 0.23,
            "net_pnl": 0.20,
            "net_pnl_usdc": 0.15,
            "equity_usdc": 1000.15,
            "reason": "TAKE_PROFIT",
        },
    ]
    (structured_dir / "decisions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    analysis = analyze_decision_logs_summary(log_dir)

    assert analysis.event_count == 4
    assert analysis.accepted_count == 2
    assert analysis.refused_count == 2
    assert analysis.total_estimated_pnl_usdc == 0.15
    assert analysis.total_fees_usdc == 0.08
    assert analysis.top_refusal_reasons[:2] == (("EDGE_INSUFFICIENT", 1), ("STALE_SIGNAL", 1))


def test_realtime_replay_cli_updates_health(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    replay = CliRunner().invoke(app, ["realtime-replay", "--from-logs", str(log_dir), "--limit", "2"])
    health = CliRunner().invoke(app, ["realtime-health", "--from-logs", str(log_dir), "--stale-after-seconds", "3600"])

    assert replay.exit_code == 0
    assert "realtime_replay=local_logs_only" in replay.output
    assert health.exit_code == 0
    assert "LIVE_REPLAY_FROM_LOCAL_LOGS" in health.output


def test_latency_report_counts_stale_signals(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    report = build_latency_report(log_dir)

    assert report.samples == 2
    assert report.stale_over_3000ms == 1
    assert report.status == "STALE_SIGNALS_PRESENT"


def test_latency_report_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_events(log_dir)

    result = CliRunner().invoke(app, ["realtime-latency-report", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "realtime_latency_report=local_logs_only" in result.output
    assert "stale_over_3000ms=1" in result.output
