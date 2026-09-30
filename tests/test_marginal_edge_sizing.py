"""[ARB #17] marginal-edge sizing : on s'arrête à la première tranche d'edge marginal ≤ 0, on ne moyenne pas."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.marginal_edge_sizing import sizing_marginal   # noqa: E402


def test_arret_a_la_tranche_negative():
    # tranches : (taille, edge_brut_bps) ; coût 5 bps -> marginal = edge-5
    tr = [(1.0, 20.0), (1.0, 10.0), (1.0, 3.0), (1.0, 50.0)]
    r = sizing_marginal(tr, cout_bps=5.0)
    assert r["n_tranches"] == 2                                  # la 3e (3-5<0) stoppe, la 4e n'est PAS reprise
    assert r["taille_totale"] == 2.0


def test_pas_de_moyennage_trompeur():
    # une tranche profonde très négative ne doit pas être ajoutée même si sa moyenne resterait >0
    tr = [(1.0, 30.0), (100.0, -100.0)]
    r = sizing_marginal(tr, cout_bps=0.0)
    assert r["taille_totale"] == 1.0                            # on n'avale pas la tranche négative


def test_net_moyen_positif():
    r = sizing_marginal([(2.0, 20.0)], cout_bps=5.0)
    assert r["net_moyen_bps"] == 15.0
