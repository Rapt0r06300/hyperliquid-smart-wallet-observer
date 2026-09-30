"""[COPY-VAULT #85] fill batching window : rafale de micro-fills d'un oid compressée avant réplication."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.fill_batching_window import FenetreBatch   # noqa: E402


def test_compression_apres_fenetre():
    fb = FenetreBatch(fenetre_ms=250.0)
    fb.ajouter("oid1", 1.0, 100.0, now_ms=1000.0)
    fb.ajouter("oid1", 3.0, 104.0, now_ms=1100.0)        # même fenêtre
    assert fb.prete("oid1", now_ms=1200.0)["prete"] is False   # fenêtre pas écoulée
    agg = fb.prete("oid1", now_ms=1300.0)                # 300ms > 250ms
    assert agg["prete"] is True and agg["qte"] == 4.0 and agg["vwap"] == 103.0


def test_vide_apres_emission():
    fb = FenetreBatch(fenetre_ms=100.0)
    fb.ajouter("oid1", 1.0, 100.0, now_ms=0.0)
    fb.prete("oid1", now_ms=200.0)
    assert fb.prete("oid1", now_ms=300.0)["prete"] is False   # lot consommé


def test_fill_invalide():
    fb = FenetreBatch()
    assert fb.ajouter("oid1", 0.0, 100.0, now_ms=0.0)["ok"] is False
