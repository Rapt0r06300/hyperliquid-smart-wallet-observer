"""Q-274 — Snapshot tests des rapports (stables).

Vérifie que les rapports produits par le système ont une structure
déterministe et stable entre les runs.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest


def test_daily_summary_structure():
    from hl_observer.ops.rapport_quotidien import build_daily_summary

    with patch("time.strftime", return_value="2026-01-15"), \
         patch("time.time", return_value=1736899200.0):
        report = build_daily_summary(
            pnl_usd=12.5,
            fees_usd=1.8,
            trades_count=7,
            positions_open=2,
            max_drawdown_pct=3.2,
            uptime_pct=98.5,
            alerts=["spread anormal BTC"],
        )

    assert report["date"] == "2026-01-15"
    assert report["pnl_usd"] == 12.5
    assert report["fees_usd"] == 1.8
    assert report["pnl_net_usd"] == 10.7
    assert report["trades_count"] == 7
    assert report["positions_open"] == 2
    assert report["max_drawdown_pct"] == 3.2
    assert report["uptime_pct"] == 98.5
    assert report["alerts"] == ["spread anormal BTC"]


def test_daily_summary_defaults():
    from hl_observer.ops.rapport_quotidien import build_daily_summary

    report = build_daily_summary()
    assert report["pnl_usd"] == 0.0
    assert report["fees_usd"] == 0.0
    assert report["trades_count"] == 0
    assert report["alerts"] == []


def test_daily_summary_extra_fields():
    from hl_observer.ops.rapport_quotidien import build_daily_summary

    report = build_daily_summary(extra={"sharpe": 1.5, "win_rate": 0.6})
    assert report["extra"]["sharpe"] == 1.5


def test_sante_journal_append_and_read(tmp_path, monkeypatch):
    from hl_observer.ops import sante_journal

    journal_file = tmp_path / "sante_journal.jsonl"
    monkeypatch.setenv("HYPERSMART_SANTE_JOURNAL", str(journal_file))

    sante_journal.append("HEARTBEAT", source="test", detail={"ok": True})
    sante_journal.append("DEGRADATION", source="BBO", level="WARNING")

    entries = sante_journal.read_recent(10)
    assert len(entries) == 2
    assert entries[0]["type"] == "HEARTBEAT"
    assert entries[0]["source"] == "test"
    assert entries[1]["type"] == "DEGRADATION"
    assert entries[1]["level"] == "WARNING"


def test_sante_journal_empty_read(tmp_path, monkeypatch):
    from hl_observer.ops import sante_journal

    monkeypatch.setenv("HYPERSMART_SANTE_JOURNAL", str(tmp_path / "nope.jsonl"))
    assert sante_journal.read_recent() == []
