"""[lot2 #81] ping-pong suppression : après fills répétés d'un côté, suppression des quotes de ce côté."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.ping_pong_suppression import SuppressionPingPong   # noqa: E402


def test_suppression_apres_seuil():
    s = SuppressionPingPong(seuil_fills=3, fenetre_ms=10_000.0)
    for t in (0.0, 1000.0, 2000.0):
        s.enregistrer_fill("BTC", "BUY", now_ms=t)
    r = s.peut_quoter("BTC", "BUY", now_ms=2500.0)
    assert r["peut_quoter"] is False and r["raison"] == "PING_PONG_SUPPRIME_CE_COTE"


def test_autre_cote_libre():
    s = SuppressionPingPong(seuil_fills=1)
    s.enregistrer_fill("BTC", "BUY", now_ms=0.0)
    assert s.peut_quoter("BTC", "SELL", now_ms=100.0)["peut_quoter"] is True


def test_hors_fenetre_libere():
    s = SuppressionPingPong(seuil_fills=1, fenetre_ms=1000.0)
    s.enregistrer_fill("BTC", "BUY", now_ms=0.0)
    assert s.peut_quoter("BTC", "BUY", now_ms=5000.0)["peut_quoter"] is True
