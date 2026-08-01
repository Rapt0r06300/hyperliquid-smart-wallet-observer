"""[DATA lot2 #70] hot subscribe/unsubscribe : univers actif modifiable à chaud, idempotent."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.hot_subscribe_unsubscribe import UniversActif   # noqa: E402


def test_subscribe_idempotent():
    u = UniversActif()
    assert u.subscribe("BTC")["nouveau"] is True
    assert u.subscribe("btc")["nouveau"] is False         # déjà actif
    assert u.actifs() == ["BTC"]


def test_unsubscribe():
    u = UniversActif()
    u.subscribe("BTC")
    u.subscribe("ETH")
    assert u.unsubscribe("BTC")["retire"] is True
    assert u.actifs() == ["ETH"]


def test_actif():
    u = UniversActif()
    u.subscribe("SOL")
    assert u.actif("SOL") is True and u.actif("XRP") is False
