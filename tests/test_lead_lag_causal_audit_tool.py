from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "lead_lag_causal_audit.py"


def test_tool_is_diagnostic_only_and_preserves_economic_threshold() -> None:
    text = TOOL.read_text(encoding="utf-8")
    assert "DIAGNOSTIC_SHOCK_THRESHOLD_BPS" in text
    assert 'result["economic_threshold_unchanged"] = True' in text
    assert 'result["economic_selection_eligible"] = False' in text
    assert "detect_rolling_shocks" in text
    assert "diagnose_causal_book_coverage" in text
    assert "lead_lag_causal_coverage.json" in text
    assert "/exchange" not in text
    assert "real_execution" not in text or "economic_selection_eligible" in text
