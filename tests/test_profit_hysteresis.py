"""[ARB #23] profit hysteresis : seuil d'entrée haut, seuil de sortie bas, MAINTIEN dans la bande."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.profit_hysteresis import Hysteresis, OUVRIR, FERMER, MAINTENIR   # noqa: E402


def test_bande_evite_le_battement():
    h = Hysteresis(seuil_entree_bps=30.0, seuil_sortie_bps=10.0)
    assert h.action(35.0, ouvert=False) == OUVRIR              # au-dessus de l'entrée
    assert h.action(20.0, ouvert=True) == MAINTENIR            # dans la bande, on garde
    assert h.action(20.0, ouvert=False) == MAINTENIR           # dans la bande, on n'ouvre pas
    assert h.action(5.0, ouvert=True) == FERMER                # sous la sortie


def test_seuils_invalides_rejetes():
    try:
        Hysteresis(seuil_entree_bps=10.0, seuil_sortie_bps=30.0)
        assert False, "aurait dû lever"
    except ValueError:
        pass


def test_edge_non_mesurable_ferme_si_expose():
    h = Hysteresis(seuil_entree_bps=30.0, seuil_sortie_bps=10.0)
    assert h.action("NA", ouvert=True) == FERMER
    assert h.action("NA", ouvert=False) == MAINTENIR
