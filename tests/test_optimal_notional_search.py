"""[ARB #16] optimal notional : maximiser le PnL NET en $, pas le % (trompeur à taille infinitésimale)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import optimal_notional_search as ONS   # noqa: E402


def _cout(t):
    return 2.0 * t          # slippage linéaire : le coût croît avec la taille


def test_optimum_dollar_pas_pourcent():
    r = ONS.notional_optimal(20.0, _cout, tailles=[1.0, 3.0, 5.0, 8.0, 12.0])
    # net$(t) = t*(20-2t)/1e4 ; maximum en t=5 (le plus PETIT t a le meilleur %, mais ~0$)
    assert r["taille_optimale"] == 5.0
    assert r["net_usd"] > ONS.net_usd(1.0, 20.0, _cout)         # 5.0 rapporte plus de $ que 1.0


def test_non_mesurable_si_edge_absent():
    r = ONS.notional_optimal("NA", _cout, tailles=[1.0, 2.0])
    assert r["taille_optimale"] == "UNMEASURABLE"


def test_courbe_reportee():
    r = ONS.notional_optimal(20.0, _cout, tailles=[1.0, 5.0])
    assert len(r["courbe"]) == 2 and "net_bps" in r["courbe"][0]
