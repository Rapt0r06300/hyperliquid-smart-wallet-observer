from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.realtime.freshness_diagnostics import build_freshness_diagnostics


def _write_stale_logs(log_dir: Path) -> None:
    log_dir.mkdir(parents=True)
    rows = [
        {
            "timestamp_ms": 1,
            "coin": "ETH",
            "bot_decision": "NO_TRADE",
            "status": "REFUSED",
            "reason": "EDGE_REMAINING_TOO_LOW|STALE_SIGNAL",
            "signal_age_ms": 15_000,
            "execution": "forbidden",
            "research_only": True,
        },
        {
            "timestamp_ms": 2,
            "coin": "BTC",
            "bot_decision": "NO_TRADE",
            "status": "REFUSED",
            "reason": "NO_MATCHING_PAPER_POSITION_FOR_CLOSE",
            "signal_age_ms": 20_000,
            "execution": "forbidden",
            "research_only": True,
        },
        {
            "timestamp_ms": 3,
            "coin": "SOL",
            "bot_decision": "PAPER_ENTRY_REPLAYED",
            "status": "LOCAL_REPLAY",
            "signal_age_ms": 100,
            "estimated_net_pnl_usdc": 0.1,
            "execution": "forbidden",
            "research_only": True,
        },
    ]
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_freshness_diagnostics_recommends_when_stale_dominates(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_stale_logs(log_dir)

    report = build_freshness_diagnostics(log_dir)

    codes = {item.code for item in report.recommendations}
    assert report.stale_ratio == 0.666667
    assert "STALE_RATIO_TOO_HIGH" in codes
    assert "P95_LATENCY_TOO_HIGH" in codes


def test_freshness_diagnostics_cli(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    _write_stale_logs(log_dir)

    result = CliRunner().invoke(app, ["freshness-diagnostics", "--from-logs", str(log_dir)])

    assert result.exit_code == 0
    assert "freshness_diagnostics=simulation_only" in result.output
    assert "STALE_RATIO_TOO_HIGH" in result.output
    assert "recommandations" not in result.output.lower()

