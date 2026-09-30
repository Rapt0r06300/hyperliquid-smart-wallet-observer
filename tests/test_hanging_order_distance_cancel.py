"""[CROSS-VENUE lot2 #76] hanging-order distance cancellation : ordre gardé tant qu'il reste proche du marché."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.hanging_order_distance_cancel import decision, GARDER, ANNULER   # noqa: E402


def test_dans_la_distance_garde():
    r = decision(100.1, 100.0, distance_max_bps=30.0)    # 10 bps
    assert r["decision"] == GARDER and r["distance_bps"] == 10.0


def test_trop_loin_annule():
    r = decision(101.0, 100.0, distance_max_bps=30.0)    # 100 bps
    assert r["decision"] == ANNULER and r["raison"] == "TROP_LOIN_DU_MARCHE"


def test_prix_invalide_annule():
    assert decision("x", 100.0)["decision"] == ANNULER
