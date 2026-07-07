"""Priority 2 guard: the PS1 launcher must keep the calibrated freshness guard.

HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=15000 is read by the hl_observer stack
(signal_detector / ui). Anything beyond the hard 2x cap is ignored before
scoring. The dYdX value DYDX_MAX_SIGNAL_AGE_MS stays independent.
"""

from pathlib import Path

PS1 = Path("tools/start_hypersmart_simulation.ps1")


def test_start_script_keeps_calibrated_freshness_guard():
    text = PS1.read_text(encoding="utf-8")
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS" "15000"' in text
    assert 'HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS = "6000"' not in text


def test_start_script_does_not_force_dydx_signal_age_to_6000():
    # The HL freshness guard must not overwrite the dYdX value (kept separate).
    text = PS1.read_text(encoding="utf-8")
    assert 'DYDX_MAX_SIGNAL_AGE_MS = "6000"' not in text
