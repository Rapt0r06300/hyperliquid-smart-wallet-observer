"""COMBIEN DE TEMPS UN COIN SORT-IL DU PLANCHER ? (idée #7)

57 % de nos relevés valent exactement 0,125 bps/h — la bande morte du clamp d'Hyperliquid.
Classer des coins tous au plancher, c'est classer du bruit (c'est ce qui a produit la
corrélation −0,596 du 21/07). Le vrai signal est : **qui sort du plancher, et combien**.

Ce que ces tests verrouillent :
  * le plancher vient de la formule PUBLIQUE de la venue, pas d'une constante à nous ;
  * un pourcentage sur trop peu d'observations est EXCLU, pas relégué ;
  * le module décrit un passé, il ne prédit rien (et le dit).
"""
from __future__ import annotations

import pytest

from hl_observer.funding.funding_hors_plancher import (OBSERVATIONS_MIN, classement,
                                                       est_hors_plancher, profil, resume)
from hl_observer.funding.funding_previsionnel import TAUX_INTERET_BPS_H


def _lignes(coin, valeurs):
    return [{"coin": coin, "funding_bps_h": v} for v in valeurs]


def test_le_plancher_vient_de_la_formule_de_la_VENUE():
    """0,125 bps/h = taux d'intérêt du protocole. Pas un seuil qu'on aurait choisi."""
    assert TAUX_INTERET_BPS_H == 0.125
    assert est_hors_plancher(0.125) is False
    assert est_hors_plancher(0.124) is False
    # une marge anti-bruit d'arrondi : 0,126 reste « au plancher », 0,14 en sort vraiment.
    assert est_hors_plancher(0.126) is False
    assert est_hors_plancher(0.14) is True


@pytest.mark.parametrize("v", [None, "0.5", True, float("nan"), [1]])
def test_une_valeur_illisible_n_est_JAMAIS_hors_plancher(v):
    assert est_hors_plancher(v) is False


def test_le_profil_compte_le_temps_passe_au_dessus():
    p = profil(_lignes("X", [0.125] * 30 + [0.5] * 10))
    assert p["X"]["observations"] == 40
    assert p["X"]["part_hors_plancher_pct"] == 25.0
    assert p["X"]["funding_max_bps_h"] == 0.5


def test_le_gain_relatif_dit_ce_que_le_coin_vaut_vs_un_coin_scotche():
    """Un coin à 0,25 de moyenne rapporte 2× un coin au plancher. C'est LE nombre qui
    justifierait de préférer un univers à un autre."""
    p = profil(_lignes("X", [0.25] * 30))
    assert p["X"]["gain_relatif_vs_plancher"] == pytest.approx(2.0)


def test_trop_peu_d_observations_est_EXCLU_pas_relegue():
    """Un pourcentage sur 3 observations est une illusion. On ne le classe pas dernier :
    on ne le classe pas du tout."""
    p = profil(_lignes("JEUNE", [0.5] * 3))
    assert p["JEUNE"]["insuffisant"] is True
    assert p["JEUNE"]["part_hors_plancher_pct"] == 100.0      # calculé...
    assert classement(_lignes("JEUNE", [0.5] * 3)) == []      # ...mais jamais classé


def test_le_classement_ordonne_par_temps_hors_plancher():
    lignes = (_lignes("SCOTCHE", [0.125] * OBSERVATIONS_MIN)
              + _lignes("PARFOIS", [0.125] * (OBSERVATIONS_MIN - 6) + [0.6] * 6)
              + _lignes("SOUVENT", [0.125] * 4 + [0.6] * (OBSERVATIONS_MIN - 4)))
    assert [c for c, _ in classement(lignes)] == ["SOUVENT", "PARFOIS", "SCOTCHE"]


def test_le_resume_DIT_quand_le_journal_est_trop_jeune():
    r = resume(_lignes("X", [0.5] * 3))
    assert r["vide"] is True and "jeune" in r["detail"]


def test_le_resume_rappelle_que_c_est_DESCRIPTIF_pas_predictif():
    r = resume(_lignes("X", [0.5] * (OBSERVATIONS_MIN + 5)))
    assert r["vide"] is False
    assert "jamais une probabilité" in r["note"] or "jamais une probabilite" in r["note"]


def test_lignes_corrompues_ignorees_sans_planter():
    assert profil([None, "pas un dict", {"coin": ""}, {"funding_bps_h": 0.5}]) == {}
