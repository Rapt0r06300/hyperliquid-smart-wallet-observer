"""[pépite 270] top/depth coherence : BBO et sommet L2 d'une même source cohérents dans tolérance stricte."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.top_depth_coherence import verifier_coherence   # noqa: E402


def test_coherent():
    r = verifier_coherence(100.0, 100.2, 100.0, 100.2, ts_bbo=1000.0, ts_l2=1010.0, tolerance_ms=50.0)
    assert r["etat"] == "COHERENT"


def test_ecart_temporel():
    r = verifier_coherence(100.0, 100.2, 100.0, 100.2, ts_bbo=1000.0, ts_l2=1200.0, tolerance_ms=50.0)
    assert r["etat"] == "INCOHERENT" and r["raison"] == "ECART_TEMPOREL"


def test_sommet_l2_differe():
    r = verifier_coherence(100.0, 100.2, 99.9, 100.2, ts_bbo=1000.0, ts_l2=1000.0)
    assert r["etat"] == "INCOHERENT" and r["raison"] == "SOMMET_L2_DIFFERE_BBO"
