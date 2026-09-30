from __future__ import annotations

import json
import os
from pathlib import Path
import time

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.realtime.realtime_health import check_realtime_health


def test_realtime_health_reports_no_events(tmp_path):
    report = check_realtime_health(tmp_path / "missing")

    assert report.status == "NO_EVENTS"
    assert report.events_seen == 0
    assert report.read_only is True
    assert report.network_required is False


def test_realtime_health_reports_local_events(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        json.dumps({"timestamp_ms": 1, "coin": "BTC", "bot_decision": "PAPER_ENTRY_REPLAYED"}) + "\n",
        encoding="utf-8",
    )

    report = check_realtime_health(log_dir, stale_after_seconds=3600)

    assert report.status == "LIVE_FROM_LOCAL_LOGS"
    assert report.events_seen == 1


def test_realtime_health_ignores_summary_cache_for_freshness(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    decision_log = log_dir / "simulation_decisions_append_only.jsonl"
    decision_log.write_text(
        json.dumps({"timestamp_ms": 1, "coin": "BTC", "bot_decision": "PAPER_ENTRY_REPLAYED"}) + "\n",
        encoding="utf-8",
    )
    old_time = time.time() - 3_600
    os.utime(decision_log, (old_time, old_time))
    (log_dir / "simulation_log_summary_cache.json").write_text(
        json.dumps({"cache": "fresh but not a realtime event"}),
        encoding="utf-8",
    )

    report = check_realtime_health(log_dir, stale_after_seconds=1)

    assert report.status == "STALE"
    assert report.events_seen == 1


def test_realtime_health_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        json.dumps({"timestamp_ms": 1, "coin": "BTC", "bot_decision": "PAPER_ENTRY_REPLAYED"}) + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["realtime-health", "--from-logs", str(log_dir), "--stale-after-seconds", "3600"])

    assert result.exit_code == 0
    assert "realtime_health=local_read_only" in result.output
    assert "network_required=false" in result.output


def test_realtime_health_surfaces_replay_write_warnings(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        json.dumps({"timestamp_ms": 1, "coin": "BTC", "bot_decision": "PAPER_ENTRY_REPLAYED"}) + "\n",
        encoding="utf-8",
    )
    (log_dir / "realtime_replay_state.json").write_text(
        json.dumps(
            {
                "replayed_at_ms": int(time.time() * 1000),
                "write_warnings": ["realtime_replay_latest.jsonl: PermissionError: locked"],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["realtime-health", "--from-logs", str(log_dir), "--stale-after-seconds", "3600"])

    assert result.exit_code == 0
    assert "replay_write_warnings=realtime_replay_latest.jsonl: PermissionError: locked" in result.output


def test_pnl_stream_cli_replays_recent_events(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        json.dumps({"timestamp_ms": 1, "coin": "BTC", "bot_decision": "PAPER_ENTRY_REPLAYED", "estimated_net_pnl_usdc": 0.1}) + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["pnl-stream", "--replay", str(log_dir)])

    assert result.exit_code == 0
    assert "pnl_stream=local_replay_only" in result.output
    assert "PAPER_ENTRY_REPLAYED" in result.output
