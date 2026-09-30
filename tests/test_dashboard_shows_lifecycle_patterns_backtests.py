"""Phase 8 (canonical): the read-only dashboard surfaces lifecycle, patterns and
backtests sections — with disclaimers, never fake movement/positions."""

from __future__ import annotations

from hyper_smart_observer.dashboard.exporter import export_dashboard
from tests.hl_runtime_fakes import runtime_config


def test_dashboard_has_lifecycle_pattern_backtest_sections(tmp_path):
    cfg = runtime_config(tmp_path)
    html = export_dashboard(cfg).read_text(encoding="utf-8")
    assert "Position Lifecycle" in html
    assert "Pattern Detector" in html
    assert "Backtests / Replays" in html
    # research-only framing, no profit promise / no fake data
    assert "research-only" in html
    assert "No guaranteed profit" in html
    assert "no order execution exists" in html.lower()
