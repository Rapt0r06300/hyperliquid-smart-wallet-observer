"""[ARB lot2 #6] FOK symmetric arb : tout ou rien, jamais de fill partiel qui casse l'économie."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.fok_symmetric_arb import simuler_fok   # noqa: E402


def test_liquidite_suffisante_fill_complet():
    r = simuler_fok(1.0, 1.0)
    assert r["execute"] is True and r["remplie"] == 1.0


def test_liquidite_insuffisante_kill():
    r = simuler_fok(1.0, 0.6)
    assert r["execute"] is False and r["remplie"] == 0.0 and r["raison"] == "KILL_LIQUIDITE_INSUFFISANTE"


def test_entree_invalide():
    assert simuler_fok(0.0, 1.0)["remplie"] == "UNMEASURABLE"
