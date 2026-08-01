"""[pépite 226] common hedge quantum : plus petite taille hedgeable des deux côtés (PPCM des lots)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.common_hedge_quantum import quantum_commun, taille_hedgeable   # noqa: E402


def test_ppcm_des_lots():
    r = quantum_commun(0.1, 0.15)                         # PPCM(0.1, 0.15) = 0.3
    assert abs(r["quantum"] - 0.3) < 1e-9


def test_taille_hedgeable():
    r = taille_hedgeable(1.0, lot_a=0.1, lot_b=0.15)      # quantum 0.3 -> plus grand multiple <= 1.0 = 0.9
    assert abs(r["taille"] - 0.9) < 1e-9 and r["residu_evite"] is True


def test_lot_invalide():
    assert quantum_commun(0.0, 0.1)["quantum"] == "UNMEASURABLE"
