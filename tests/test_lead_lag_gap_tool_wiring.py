from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "diagnose_lead_lag_collection_gap.py"
WORKER = ROOT / "src" / "hl_observer" / "ops" / "family_economic_job.py"


def test_diagnostic_tool_garde_le_seuil_economique_intact() -> None:
    text = TOOL.read_text(encoding="utf-8")
    assert "DEFAULT_DIAGNOSTIC_THRESHOLD_BPS = 8.0" in text
    assert "SHOCK_THRESHOLD_BPS" in text
    assert '"economic_threshold_bps_unchanged"' in text
    assert '"diagnostic_threshold_changes_economic_strategy": False' in text
    assert '"paper_read_only": True' in text
    assert '"real_execution": False' in text


def test_worker_full_lancera_l_autopsie_lead_lag() -> None:
    text = WORKER.read_text(encoding="utf-8")
    assert 'request["suite"] == "lead-lag-full"' in text
    assert "diagnose_lead_lag_collection_gap.py" in text
    assert '"--diagnostic-threshold-bps", "8.0"' in text
    assert '"--max-book-delay-ms", "750"' in text
    assert "lead_lag_collection_gap_diagnostic.json" in text
