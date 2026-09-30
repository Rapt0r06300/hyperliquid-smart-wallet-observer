"""[pépite 254] subscription ACK state : actif seulement après acquittement explicite."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.subscription_ack_state import EtatAbonnements   # noqa: E402


def test_demande_pas_active_avant_ack():
    e = EtatAbonnements()
    e.demander("l2Book:BTC")
    assert e.est_actif("l2Book:BTC") is False
    assert e.donnee_admissible("l2Book:BTC")["admissible"] is False
    e.acquitter("l2Book:BTC")
    assert e.est_actif("l2Book:BTC") is True and e.donnee_admissible("l2Book:BTC")["admissible"] is True


def test_ack_sans_demande_refuse():
    e = EtatAbonnements()
    assert e.acquitter("trades:ETH")["ok"] is False and e.est_actif("trades:ETH") is False


def test_actifs_et_canal_invalide():
    e = EtatAbonnements()
    e.demander("a"); e.acquitter("a"); e.demander("b")
    assert e.actifs() == {"a"} and e.demander("")["ok"] is False
