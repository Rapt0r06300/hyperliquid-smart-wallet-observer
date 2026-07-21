"""LE SEUIL DE PRISE DE PROFIT, DÉRIVÉ DU BRUIT (P1-8, 21/07).

LA MESURE
---------
À notre notionnel (233 $/position), le bruit d'accrual vaut **0,0029 $/h** et le seuil fixe
de 0,05 $ vaut **17,2× le bruit**. Il tient aujourd'hui.

Mais un seuil FIXE contre un bruit PROPORTIONNEL au notionnel se dégrade **en silence** : à
10× le notionnel, le bruit vaut 0,029 $/h et le ratio tombe à 1,7×. On prendrait des profits
sur de la comptabilité, sans qu'aucune alarme ne sonne.

Même motif que le plafond de break-even : un seuil **choisi** se défend par une opinion, un
seuil **dérivé** se défend par une contrainte.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_position_lifecycle import (MULTIPLE_BRUIT_PRISE_PROFIT,
                                                          SEUIL_PRISE_PROFIT_USD,
                                                          seuil_prise_profit)


def test_le_seuil_vaut_PLUSIEURS_fois_le_bruit_d_accrual():
    """Le bruit = une heure de funding sur le notionnel (l'incertitude max du découpage
    réglé/estimé). Un seuil qui vaut le bruit déclenche sur du bruit."""
    for notional in (233.0, 1_000.0, 10_000.0, 100_000.0):
        bruit_h = notional * 0.125 / 1e4
        s = seuil_prise_profit(notional, 0.125)
        assert s >= MULTIPLE_BRUIT_PRISE_PROFIT * bruit_h - 1e-9 or s == SEUIL_PRISE_PROFIT_USD


def test_le_seuil_SUIT_le_notionnel():
    """C'est tout l'intérêt : un seuil fixe se serait dégradé en silence."""
    seuils = [seuil_prise_profit(n, 0.125) for n in (233.0, 1_000.0, 10_000.0)]
    assert seuils == sorted(seuils)
    assert seuils[-1] > seuils[0] * 5


def test_le_plancher_historique_est_CONSERVE():
    """À petit notionnel, le seuil dérivé passerait sous 0,05 $ — on ne descend pas."""
    assert seuil_prise_profit(10.0, 0.125) == SEUIL_PRISE_PROFIT_USD


@pytest.mark.parametrize("n, f", [(None, 0.125), (233.0, None), (0.0, 0.125), (233.0, 0.0),
                                  (-5.0, 0.125), (float("nan"), 0.125), (True, 0.125)])
def test_donnee_absente_retombe_sur_le_PLANCHER_jamais_plus_bas(n, f):
    """On ne baisse JAMAIS une garde faute d'information."""
    assert seuil_prise_profit(n, f) == SEUIL_PRISE_PROFIT_USD


def test_un_funding_plus_eleve_exige_un_seuil_plus_haut():
    """Plus le funding coule vite, plus le bruit d'une heure est gros."""
    assert seuil_prise_profit(10_000.0, 0.5) > seuil_prise_profit(10_000.0, 0.125)


def test_la_marge_mesuree_est_SUPERIEURE_a_5():
    """Sous 5×, un seuil ne protège plus de la comptabilité. Mesuré 17,2× le 21/07."""
    assert MULTIPLE_BRUIT_PRISE_PROFIT >= 5.0


def test_le_seuil_DERIVE_est_BRANCHE_dans_la_sortie():
    """Testé ≠ branché : si la sortie utilise encore la constante, la dérivation ne sert
    à rien."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "funding"
           / "carry_position_lifecycle.py").read_text(encoding="utf-8")
    assert "seuil_prise_profit(position.get(\"notional_usdt\")" in src, \
        "la sortie prise-de-profit n'appelle pas le seuil dérivé"
