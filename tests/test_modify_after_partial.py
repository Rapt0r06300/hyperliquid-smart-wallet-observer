"""[pépite 224] modify-after-partial : après 37% rempli + modif, on travaille sur le remaining correct."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.modify_after_partial import quantite_travaillante   # noqa: E402


def test_remaining_correct():
    r = quantite_travaillante(quantite_initiale=1.0, deja_rempli=0.37, nouvelle_cible=0.8)
    assert r["remaining"] == 0.43                         # 0.8 - 0.37, pas 0.8


def test_nouvelle_cible_sous_rempli():
    r = quantite_travaillante(quantite_initiale=1.0, deja_rempli=0.5, nouvelle_cible=0.3)
    assert r["remaining"] == 0.0                          # deja sur-rempli vs nouvelle cible


def test_entree_invalide():
    assert quantite_travaillante(quantite_initiale=1.0, deja_rempli=None, nouvelle_cible=0.8)["remaining"] == "UNMEASURABLE"
