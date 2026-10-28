from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "run_dataset_economic_campaigns.py"


def test_full_cold_launcher_does_not_wire_disabled_lead_lag_diagnostics() -> None:
    text = TOOL.read_text(encoding="utf-8", errors="replace")

    assert "_lead_lag_diagnostic_overrides" not in text
    assert "DIAGNOSTIC_SHOCK_THRESHOLD_BPS" not in text
    assert 'load_family_source_paths(data_root, "lead_lag")' not in text
    assert "install_cross_venue_adapter" not in text
    assert "lead_consumed=[]" in text
    assert "cross_consumed=[]" in text
    assert '"lead_lag": "DISABLED_BY_SCOPE"' in text
