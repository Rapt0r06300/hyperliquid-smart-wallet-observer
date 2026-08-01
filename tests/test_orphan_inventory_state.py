"""[ARB #41] orphan inventory state : jambes non appariées -> UNHEDGED_RESIDUAL, jamais 'terminé'."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import orphan_inventory_state as OIS   # noqa: E402


def test_apparie_est_hedged():
    r = OIS.etat_inventaire(1.0, 1.0)
    assert r["etat"] == OIS.HEDGED and r["residu"] == 0.0


def test_residu_nu_explicite():
    r = OIS.etat_inventaire(1.0, 0.6)
    assert r["etat"] == OIS.UNHEDGED_RESIDUAL and r["residu"] == 0.4 and r["termine"] is False


def test_quantite_inconnue_prudence():
    r = OIS.etat_inventaire(1.0, None)
    assert r["etat"] == OIS.UNHEDGED_RESIDUAL                         # jamais 'couvert' sans preuve
    assert OIS.etat_inventaire(1.0, 0.6, hold=True)["etat"] == OIS.POSITION_HOLD
