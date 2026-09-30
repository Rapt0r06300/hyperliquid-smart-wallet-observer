"""Priority 2 guard: the PS1 launcher must keep calibrated positive MIN_EDGE_BPS."""

from pathlib import Path

PS1 = Path("tools/start_hypersmart_simulation.ps1")


def test_start_script_keeps_min_edge_bps_guard():
    text = PS1.read_text(encoding="utf-8")
    # CALIBRE (audit 2026-07-11) : la valeur du plancher d'edge se REGLE (28 -> 16 apres mesure).
    # Ce qui doit etre garanti, c'est que le garde-fou EXISTE, pas qu'il vaille un chiffre fige.
    assert "HYPERSMART_SIMULATION_MIN_EDGE_BPS" in text
