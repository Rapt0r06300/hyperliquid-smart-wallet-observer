"""Section 8: the long-form master plan exists and states the core doctrine."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_master_plan_present_and_states_doctrine():
    plan = ROOT / "docs" / "CODEX_HYPERSMART_MASTER_PLAN_V6.md"
    assert plan.exists(), "docs/CODEX_HYPERSMART_MASTER_PLAN_V6.md missing"
    text = plan.read_text(encoding="utf-8", errors="ignore").lower()
    assert "simulation" in text and "read-only" in text
    assert "hyperliquid" in text
    assert "/exchange" in text  # must name the banned endpoint to prohibit it
    for marker in ("ticket 05", "ticket 17", "ticket 22"):
        assert marker in text, f"{marker} section missing from V6 plan"
