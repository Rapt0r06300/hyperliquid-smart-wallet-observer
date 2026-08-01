"""[COPY-VAULT #53] dual sizing cap : taille finale = min(equity_based, liquidity_based)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.dual_sizing_cap import taille_finale   # noqa: E402


def test_min_des_deux():
    r = taille_finale(0.5, 0.3)
    assert r["taille"] == 0.3 and r["contrainte"] == "LIQUIDITE"
    r2 = taille_finale(0.2, 0.9)
    assert r2["taille"] == 0.2 and r2["contrainte"] == "EQUITY"


def test_une_manquante_non_mesurable():
    assert taille_finale(0.5, None)["taille"] == "UNMEASURABLE"   # jamais retomber sur l'autre


def test_negatif_borne_a_zero():
    assert taille_finale(-1.0, 0.5)["taille"] == 0.0
