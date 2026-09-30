"""[ARB #12] tick/lot preflight : edge mesuré seulement sur une taille/prix RÉELLEMENT admissibles."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import tick_lot_preflight as TLP   # noqa: E402


def test_arrondi_jamais_favorable():
    assert TLP.arrondir_tick(100.037, 0.01) == 100.03          # tick INFÉRIEUR, jamais 100.04
    assert TLP.taille_admissible(1.29, lot_size=0.1) == 1.2    # plancher, jamais 1.3
    assert TLP.arrondir_tick("x", 0.01) == "UNMEASURABLE"      # entrée non numérique


def test_sous_min_lot_tombe_a_zero():
    assert TLP.taille_admissible(0.04, lot_size=0.1, min_lot=0.1) == 0.0
    pf = TLP.preflight_tick_lot(100.037, 0.04, tick=0.01, lot_size=0.1, min_lot=0.1)
    assert pf["admissible"] is False                            # taille tombée à 0 -> non exécutable


def test_admissible_reporte_la_perte_arrondi():
    pf = TLP.preflight_tick_lot(100.037, 1.29, tick=0.01, lot_size=0.1)
    assert pf["admissible"] is True
    assert pf["taille_admissible"] == 1.2
    assert round(pf["perte_arrondi"], 4) == 0.09
