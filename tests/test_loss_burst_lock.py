"""[ALL #95] per-module loss-burst lock : suspendre une clé après X pertes dans une fenêtre."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.loss_burst_lock import VerrouPertes   # noqa: E402


def test_verrou_apres_seuil():
    v = VerrouPertes(seuil_pertes=3, fenetre_ms=60_000.0, duree_lock_ms=300_000.0)
    v.enregistrer_perte("BTC:LONG", now_ms=0.0)
    v.enregistrer_perte("BTC:LONG", now_ms=1000.0)
    assert v.verrouille("BTC:LONG", now_ms=2000.0)["verrouille"] is False
    r = v.enregistrer_perte("BTC:LONG", now_ms=2000.0)   # 3e perte
    assert r["verrouille"] is True
    assert v.verrouille("BTC:LONG", now_ms=3000.0)["verrouille"] is True


def test_lock_expire():
    v = VerrouPertes(seuil_pertes=1, duree_lock_ms=300_000.0)
    v.enregistrer_perte("ETH", now_ms=0.0)
    assert v.verrouille("ETH", now_ms=400_000.0)["verrouille"] is False


def test_hors_fenetre_ne_declenche_pas():
    v = VerrouPertes(seuil_pertes=2, fenetre_ms=1000.0)
    v.enregistrer_perte("SOL", now_ms=0.0)
    r = v.enregistrer_perte("SOL", now_ms=5000.0)        # 1re hors fenêtre
    assert r["verrouille"] is False
