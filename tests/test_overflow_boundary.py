"""[pépite 221] overflow boundary : détecter dépassement de la borne d'exactitude."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.accounting.overflow_boundary import dans_bornes, produit_sur, MAX_ENTIER_SUR   # noqa: E402


def test_dans_bornes():
    assert dans_bornes(1000.0)["ok"] is True
    assert dans_bornes(float(MAX_ENTIER_SUR) * 2)["ok"] is False


def test_non_finie():
    assert dans_bornes(float("inf"))["ok"] is False


def test_produit_overflow():
    r = produit_sur(1e10, 1e10)                           # 1e20 > 2^53
    assert r["ok"] is False and r["raison"] == "DEPASSE_BORNE_OVERFLOW"
