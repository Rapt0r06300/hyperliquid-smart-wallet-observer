"""[ARB #7] depeg haircut : marge de sécurité qui grandit avec l'écart du stable au dollar."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import depeg_haircut as DH   # noqa: E402


def test_pas_de_haircut_sous_le_seuil_puis_croit():
    assert DH.haircut_depeg_bps(0.9995, seuil_bps=20.0)["haircut_bps"] == 0.0        # 5 bps depeg < seuil 20
    fort = DH.haircut_depeg_bps(0.985, seuil_bps=20.0, facteur=1.0)                  # 150 bps depeg
    assert fort["haircut_bps"] == 130.0 and fort["au_dela_du_seuil"] is True         # (150-20)*1.0


def test_edge_apres_haircut_et_unmeasurable():
    assert DH.edge_apres_haircut(50.0, 0.985, seuil_bps=20.0) == round(50.0 - 130.0, 4)   # edge décoté (<0)
    assert DH.edge_apres_haircut(50.0, None) == "UNMEASURABLE"                            # prix stable absent
