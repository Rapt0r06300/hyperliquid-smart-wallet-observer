"""[pépite 250] dust accumulator : cumuler des résidus jusqu'à une fermeture exécutable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.dust_accumulator import AccumulateurDust   # noqa: E402


def test_cumul_devient_executable():
    acc = AccumulateurDust(min_notional=10.0)
    r1 = acc.ajouter("BTC", 0.05, prix=100.0)            # 5$ < 10$
    assert r1["executable"] is False
    r2 = acc.ajouter("BTC", 0.06, prix=100.0)            # cumul 0.11 -> 11$ >= 10$
    assert r2["executable"] is True


def test_vider():
    acc = AccumulateurDust(min_notional=10.0)
    acc.ajouter("BTC", 0.2, prix=100.0)
    acc.vider("BTC")
    assert acc.ajouter("BTC", 0.01, prix=100.0)["cumul_qte"] == 0.01


def test_donnee_invalide():
    assert AccumulateurDust(min_notional=10.0).ajouter("BTC", 0.1, prix=0.0)["ok"] is False
