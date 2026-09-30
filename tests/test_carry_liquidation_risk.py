"""T2b / #588 — LA JAMBE PERP PEUT ETRE LIQUIDEE. Tests du chiffrage.

Le carry HYPE (T2) est le SEUL resultat positif du projet qui ait survecu a une falsification.
Raison de plus pour ne pas le laisser vivre avec un risque non modelise : *un chiffre qu'on aime
est celui qu'on doit attaquer le plus fort.*

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_liquidation_risk import (
    MOTIF_DONNEE_MANQUANTE,
    MOTIF_LIQUIDE_PAR_LE_PASSE,
    MOTIF_MARGE_SOUS_MAINTENANCE,
    MOTIF_OK,
    evaluer_risque_liquidation,
    fraction_marge_maintenance,
    marge_requise_pour_survivre,
    mouvement_adverse_de_liquidation,
    perte_seche_si_backstop,
    pire_hausse_sur_fenetre,
    rendement_sur_capital_total,
)

# ====================================================== 1. LA DOC OFFICIELLE, EN CHIFFRES


def test_la_marge_de_maintenance_est_la_MOITIE_de_la_marge_initiale_au_levier_MAX():
    """Doc Hyperliquid : « between 1.25 % (for 40x max leverage assets) and 16.7 % (for 3x) »."""
    assert fraction_marge_maintenance(40.0) == pytest.approx(0.0125)
    assert fraction_marge_maintenance(3.0) == pytest.approx(0.16666, rel=1e-3)


def test_un_levier_max_absurde_est_refuse():
    with pytest.raises(ValueError):
        fraction_marge_maintenance(0.0)


# ====================================================== 2. LE MOUVEMENT QUI LIQUIDE


def test_la_formule_de_liquidation_est_l_INVERSE_de_la_marge_requise():
    """Un aller-retour : si je dimensionne la marge pour survivre a +40 %, alors le mouvement
    liquidant DOIT etre exactement +40 %. Sinon l'une des deux formules ment."""
    mm = fraction_marge_maintenance(5.0)
    m = marge_requise_pour_survivre(0.40, mm)
    assert mouvement_adverse_de_liquidation(m, mm) == pytest.approx(0.40, rel=1e-9)


def test_une_marge_SOUS_la_maintenance_est_liquidable_des_l_entree():
    mm = fraction_marge_maintenance(5.0)          # 10 %
    assert mouvement_adverse_de_liquidation(0.05, mm) < 0.0


def test_plus_la_marge_est_grosse_plus_le_tampon_est_grand():
    mm = fraction_marge_maintenance(5.0)
    faible = mouvement_adverse_de_liquidation(0.20, mm)
    forte = mouvement_adverse_de_liquidation(0.60, mm)
    assert forte > faible > 0.0


# ====================================================== 3. 🔴 LE COUT QUE T2 N'AVAIT PAS COMPTE


def test_le_rendement_se_calcule_sur_le_CAPITAL_TOTAL_pas_sur_le_notionnel():
    """Le spot est paye CASH. Le capital immobilise est N + M, pas N.

    T2 annoncait « +33,6 bps sur 500 $ » en comptant N seul. Avec une marge egale au notionnel
    (m = 1), le MEME carry ne rend plus que la moitie.
    """
    assert rendement_sur_capital_total(33.6, 0.0) == pytest.approx(33.6)
    assert rendement_sur_capital_total(33.6, 1.0) == pytest.approx(16.8)
    assert rendement_sur_capital_total(33.6, 0.5) == pytest.approx(22.4)


def test_le_tampon_et_le_rendement_TIRENT_EN_SENS_INVERSE():
    """C'est LE point de la tache : on ne peut pas avoir les deux. Un test qui le fige."""
    mm = fraction_marge_maintenance(5.0)
    rendements = []
    tampons = []
    for m in (0.15, 0.30, 0.60, 1.00):
        tampons.append(mouvement_adverse_de_liquidation(m, mm))
        rendements.append(rendement_sur_capital_total(33.6, m))
    assert tampons == sorted(tampons)                     # le tampon MONTE
    assert rendements == sorted(rendements, reverse=True)  # le rendement DESCEND


# ====================================================== 4. LE BACKSTOP (perte SECHE)


def test_le_backstop_confisque_la_marge_de_maintenance_ni_plus_ni_moins():
    """Doc : « the maintenance margin is not returned to the user ».

    Il ne faut NI minimiser (c'est une vraie perte seche) NI exagerer (ce n'est PAS « on perd
    tout » : la jambe spot absorbe la perte de prix du short).
    """
    mm = fraction_marge_maintenance(5.0)                  # 10 %
    assert perte_seche_si_backstop(mm, 500.0) == pytest.approx(50.0)


# ====================================================== 5. LA MESURE SUR PRIX (causale)


def test_la_pire_hausse_ne_regarde_que_le_FUTUR_de_chaque_entree():
    prix = [100.0, 110.0, 100.0, 100.0]
    # entree a 100 -> voit 110 dans la fenetre 1 -> +10 %
    assert pire_hausse_sur_fenetre(prix, 1) == pytest.approx(0.10)


def test_une_serie_qui_ne_monte_JAMAIS_donne_zero():
    assert pire_hausse_sur_fenetre([100.0, 99.0, 98.0, 97.0], 3) == pytest.approx(0.0)


def test_une_fenetre_plus_longue_ne_peut_pas_donner_une_pire_hausse_PLUS_PETITE():
    prix = [100.0, 101.0, 130.0, 90.0]
    assert pire_hausse_sur_fenetre(prix, 3) >= pire_hausse_sur_fenetre(prix, 1)


# ====================================================== 6. LE VERDICT (deny-by-default)


def test_une_donnee_manquante_est_TOUJOURS_un_refus():
    base = dict(coin="HYPE", levier_max=5.0, marge_ratio=0.5,
                pire_mouvement_observe=0.20, rendement_brut_bps=33.6)
    for cle in ("levier_max", "marge_ratio", "pire_mouvement_observe", "rendement_brut_bps"):
        args = dict(base)
        args[cle] = None
        v = evaluer_risque_liquidation(**args)
        assert v.viable is False
        assert v.motif == MOTIF_DONNEE_MANQUANTE


def test_une_marge_TROP_FINE_est_liquidable_des_l_entree_et_refusee():
    v = evaluer_risque_liquidation(coin="HYPE", levier_max=3.0, marge_ratio=0.10,
                                   pire_mouvement_observe=0.20, rendement_brut_bps=33.6)
    assert v.viable is False
    assert v.motif == MOTIF_MARGE_SOUS_MAINTENANCE


def test_LE_GARDE_FOU_MORD_quand_le_PIRE_MOUVEMENT_REEL_aurait_liquide():
    """LE test de la tache. Marge de 30 %, levier max 5x -> liquide a +18,2 %.
    Si le prix a REELLEMENT monte de +45 % pendant une periode de detention, la jambe perp
    serait morte -- et on serait retombe LONG SPOT SEC, la zone morte deja enterree."""
    v = evaluer_risque_liquidation(coin="HYPE", levier_max=5.0, marge_ratio=0.30,
                                   pire_mouvement_observe=0.45, rendement_brut_bps=33.6)
    assert v.survit is False
    assert v.viable is False
    assert v.motif == MOTIF_LIQUIDE_PAR_LE_PASSE
    assert "FUNDING_JAMBE_NUE" in v.note


def test_une_marge_SUFFISANTE_passe___mais_le_rendement_est_DIVISE():
    """Et c'est tout le prix a payer : le carry survit, mais il ne rend plus la meme chose."""
    v = evaluer_risque_liquidation(coin="HYPE", levier_max=5.0, marge_ratio=0.60,
                                   pire_mouvement_observe=0.40, rendement_brut_bps=33.6)
    assert v.survit is True
    assert v.viable is True
    assert v.motif == MOTIF_OK
    assert v.rendement_sur_capital_bps == pytest.approx(33.6 / 1.6, rel=1e-6)
    assert v.rendement_sur_capital_bps < v.rendement_brut_bps


def test_la_marge_calculee_pour_survivre_EXACTEMENT_est_jugee_SURVIVANTE():
    """🚩 UN BUG DE BORNE DANS MON PROPRE VERDICT, fige ici.

    `marge_requise_pour_survivre(r)` rend le m qui liquide *exactement* a +r. Avec un `>` strict,
    ce m etait declare NON SURVIVANT -- et le rapport imprimait « il aurait fallu +95,6 % ; le prix
    a monte de +95,6 % ». Une phrase qui se contredit elle-meme sera lue comme fausse, meme quand
    le chiffre est juste.
    """
    mm = fraction_marge_maintenance(10.0)
    m = marge_requise_pour_survivre(0.956, mm)
    v = evaluer_risque_liquidation(coin="HYPE", levier_max=10.0, marge_ratio=m,
                                   pire_mouvement_observe=0.956, rendement_brut_bps=33.6)
    assert v.survit is True
    assert v.motif == MOTIF_OK


def test_le_verdict_ne_pretend_JAMAIS_une_execution_reelle():
    v = evaluer_risque_liquidation(coin="HYPE", levier_max=5.0, marge_ratio=0.60,
                                   pire_mouvement_observe=0.10, rendement_brut_bps=33.6)
    assert v.as_dict()["real_execution"] is False
