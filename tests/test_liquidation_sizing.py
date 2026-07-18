"""Sizing liquidation — taille proportionnelle à la purge, 0 si pas une vraie purge ; combo funding."""
from __future__ import annotations

from hl_observer.backtesting.liquidation_sizing import combo_liquidation_funding, facteur_taille_cascade


def test_taille_proportionnelle_bornee():
    assert facteur_taille_cascade(None) == 0.0
    assert facteur_taille_cascade(10_000.0) == 0.0          # < purge min -> pas de trade
    assert facteur_taille_cascade(500_000.0) == 0.5         # 500k / 1M ref
    assert facteur_taille_cascade(5_000_000.0) == 1.5       # bornée (plafond)
    assert facteur_taille_cascade(200_000.0) < facteur_taille_cascade(800_000.0)  # plus gros = plus de taille


def test_combo_aligne_renforce_la_conviction():
    r = combo_liquidation_funding("LONG", -0.8)             # longs liquidés + funding très négatif = haussier
    assert r["aligne"] is True and r["facteur_conviction"] > 1.0
    r2 = combo_liquidation_funding("LONG", +0.8)            # sens opposé -> pas d'alignement
    assert r2["aligne"] is False and r2["facteur_conviction"] == 1.0
    r3 = combo_liquidation_funding("LONG", -0.1)            # choc trop faible
    assert r3["aligne"] is False
