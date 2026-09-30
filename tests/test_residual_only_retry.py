"""[ARB #33] residual-only retry : on ne re-tente que la quantité non couverte, jamais l'ordre entier."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.residual_only_retry import quantite_a_retry   # noqa: E402


def test_retry_du_residu():
    r = quantite_a_retry(1.0, 0.6)
    assert r["qte_retry"] == 0.4 and r["termine"] is False            # 0.4 restant, pas 1.0


def test_termine_si_tout_couvert():
    r = quantite_a_retry(1.0, 1.0)
    assert r["qte_retry"] == 0.0 and r["termine"] is True


def test_etat_inconnu_non_mesurable():
    assert quantite_a_retry(1.0, None)["qte_retry"] == "UNMEASURABLE"
