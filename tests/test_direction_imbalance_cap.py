"""[ARB #27] direction imbalance cap : plafonner les exécuteurs empilant le même risque directionnel."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.direction_imbalance_cap import CapImbalanceDirection   # noqa: E402


def test_plafond_par_direction():
    cap = CapImbalanceDirection(cap_par_direction=2)
    assert cap.ajouter("BTC", +1) is True
    assert cap.ajouter("BTC", +1) is True
    assert cap.peut_ajouter("BTC", +1)["ok"] is False           # cap atteint
    assert cap.peut_ajouter("BTC", +1)["raison"] == "CAP_DIRECTION_ATTEINT"


def test_directions_opposees_independantes():
    cap = CapImbalanceDirection(cap_par_direction=1)
    assert cap.ajouter("BTC", +1) is True
    assert cap.ajouter("BTC", -1) is True                       # short indépendant du long
    assert cap.ajouter("BTC", +1) is False


def test_retrait_libere_une_place():
    cap = CapImbalanceDirection(cap_par_direction=1)
    cap.ajouter("ETH", +1)
    cap.retirer("ETH", +1)
    assert cap.peut_ajouter("ETH", +1)["ok"] is True
