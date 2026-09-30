"""[ARB #50] PnL decomposition : cascade gross -> slippages -> frais -> conversion -> résiduel -> net."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import pnl_decomposition as PD   # noqa: E402


def test_net_est_gross_moins_couts():
    r = PD.decomposer(gross_bps=50.0, slippage_a_bps=5.0, slippage_b_bps=4.0, frais_bps=3.0,
                      conversion_bps=1.0, residuel_bps=2.0)
    assert r["net_bps"] == 35.0 and r["cout_total_bps"] == 15.0
    assert r["cascade"][0]["poste"] == "gross_bps" and r["cascade"][-1]["cumul_bps"] == 35.0


def test_poste_manquant_net_non_chiffrable():
    r = PD.decomposer(gross_bps=50.0, slippage_a_bps=5.0, slippage_b_bps=4.0, frais_bps=None,
                      conversion_bps=1.0, residuel_bps=2.0)
    assert r["net_bps"] == "UNMEASURABLE" and "frais_bps" in r["manquants"]   # jamais comble par 0


def test_net_peut_etre_negatif():
    r = PD.decomposer(gross_bps=10.0, slippage_a_bps=6.0, slippage_b_bps=6.0, frais_bps=2.0,
                      conversion_bps=0.0, residuel_bps=0.0)
    assert r["net_bps"] == -4.0                            # coûts > dislocation -> net honnête négatif
