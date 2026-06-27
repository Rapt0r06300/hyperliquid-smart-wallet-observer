"""Priority 2 guard: the PS1 launcher must keep calibrated positive MIN_EDGE_BPS."""

from pathlib import Path

PS1 = Path("tools/start_hypersmart_simulation.ps1")


def test_start_script_keeps_min_edge_bps_guard():
    text = PS1.read_text(encoding="utf-8")
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_EDGE_BPS" "15"' in text
