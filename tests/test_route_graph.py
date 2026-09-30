"""[pépite 231] route graph : comparer le coût exécutable COMPLET, pas les seuls frais."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.route_graph import cout_total_bps, classer   # noqa: E402


def test_cout_total():
    r = {"frais_bps": 2.0, "spread_bps": 3.0, "slippage_bps": 1.0, "premium_fiabilite_bps": 1.0}
    assert cout_total_bps(r) == 7.0


def test_classement_par_cout():
    a = {"venue": "HL", "instrument": "BTC", "side": "BUY", "exec_type": "TAKER",
         "frais_bps": 2.0, "spread_bps": 1.0, "slippage_bps": 1.0, "premium_fiabilite_bps": 0.0}
    b = {"venue": "BIN", "instrument": "BTC", "side": "BUY", "exec_type": "TAKER",
         "frais_bps": 1.0, "spread_bps": 5.0, "slippage_bps": 2.0, "premium_fiabilite_bps": 0.0}
    r = classer([a, b])
    assert r["meilleure"]["cout_total_bps"] == 4.0        # A total 4 < B total 8 (malgre frais B < frais A)


def test_composant_manquant_ecarte():
    r = classer([{"venue": "X", "instrument": "Y", "side": "BUY", "exec_type": "TAKER", "frais_bps": 1.0}])
    assert r["meilleure"] is None and len(r["ecartees_non_mesurables"]) == 1
