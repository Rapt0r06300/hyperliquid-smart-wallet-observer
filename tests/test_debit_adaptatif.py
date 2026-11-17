"""LE DEBIT DU RATTRAPAGE : regle par les refus de la venue, plus devine a 10 %.

POURQUOI CE MODULE EXISTE. `BUDGET_POIDS_RATTRAPAGE_PAR_MINUTE` valait **100** unites/minute quand
le plafond que le projet se donne lui-meme vaut **1 000** (sous la limite de 1 200/min/IP). Un
rattrapage prenait donc le dixieme du debit en permanence, meme quand aucun collecteur en direct ne
demandait rien. Mesure du 15/11 : 28 s d'attente par page de funding, soit **107 heures** pour
amener 261 coins a 1 100 jours.

POURQUOI PAS LIRE LA CONSOMMATION REELLE. Parce qu'elle n'est pas mesuree : la variable
`ALINA_BUDGET_DEBIT` n'est definie NULLE PART dans le projet, et seuls 5 collecteurs sur une
vingtaine appellent `reserver_poids`. Accelerer sur un compteur qui sous-compte, c'est se garantir
des refus. On regle donc sur le seul signal que la venue donne vraiment : le refus lui-meme (AIMD).

Pur : aucune horloge, aucun reseau, aucun fichier.
"""
from __future__ import annotations

import pytest

from hl_observer.collection import debit_adaptatif as DA
from hl_observer.collection import collecte_fiable as CF


def test_le_plancher_est_l_ancien_budget_fixe():
    """On ne fait JAMAIS pire qu'avant : c'est la condition pour que ce module soit sans risque."""
    assert DA.PLANCHER_RATTRAPAGE_PAR_MINUTE == CF.BUDGET_POIDS_RATTRAPAGE_PAR_MINUTE
    cadence = DA.CadenceAimd()
    assert cadence.budget_par_minute == DA.PLANCHER_RATTRAPAGE_PAR_MINUTE
    # et la pause de depart est EXACTEMENT celle de l'ancien code
    assert cadence.pause(103.0) == pytest.approx(CF.pause_pour_poids(103.0))


def test_le_plafond_reste_sous_la_limite_partagee():
    """Le rattrapage reste le citoyen de seconde classe : de la place pour les collecteurs en direct."""
    assert DA.PLAFOND_RATTRAPAGE_PAR_MINUTE < CF.SEUIL_POIDS_PARTAGE_PAR_MINUTE
    assert CF.SEUIL_POIDS_PARTAGE_PAR_MINUTE - DA.PLAFOND_RATTRAPAGE_PAR_MINUTE >= 300.0, (
        "au moins 300 unites/min de marge : les collecteurs en direct sont EN RAFALE et n'attendent pas")


def test_montee_additive_apres_une_serie_de_succes():
    cadence = DA.CadenceAimd(succes_avant_montee=3, pas_montee=50.0)
    assert cadence.succes() == 100.0 and cadence.succes() == 100.0      # pas encore
    assert cadence.succes() == 150.0                                     # 3e succes : un cran
    for _ in range(3):
        cadence.succes()
    assert cadence.budget_par_minute == 200.0
    assert cadence.pause(100.0) == pytest.approx(30.0), "a 200 u/min, 100 unites coutent 30 s"


def test_descente_multiplicative_immediate_sur_un_refus():
    cadence = DA.CadenceAimd(succes_avant_montee=1, pas_montee=100.0)
    for _ in range(4):
        cadence.succes()
    assert cadence.budget_par_minute == 500.0
    assert cadence.refus() == 250.0, "un refus DIVISE : la limite est deja depassee, on ne negocie pas"
    assert cadence.refus() == 125.0


def test_un_refus_remet_la_serie_de_succes_a_zero():
    """Sans cela, les succes d'AVANT le refus justifieraient une montee juste APRES lui."""
    cadence = DA.CadenceAimd(succes_avant_montee=3, pas_montee=50.0)
    cadence.succes()
    cadence.succes()                       # 2 succes : il en manque 1 pour monter
    cadence.refus()                        # 100 -> 50 -> borne au plancher 100
    apres = cadence.succes()
    assert apres == DA.PLANCHER_RATTRAPAGE_PAR_MINUTE, (
        "le compteur est reparti de zero : ce succes ne doit PAS declencher la montee")


def test_le_debit_ne_descend_jamais_sous_le_plancher():
    cadence = DA.CadenceAimd()
    for _ in range(20):
        cadence.refus()
    assert cadence.budget_par_minute == DA.PLANCHER_RATTRAPAGE_PAR_MINUTE, (
        "sous le plancher, le rattrapage n'avance plus — et un rattrapage qui n'avance pas est mort")


def test_le_debit_ne_depasse_jamais_le_plafond():
    cadence = DA.CadenceAimd(succes_avant_montee=1, pas_montee=1000.0)
    for _ in range(10):
        cadence.succes()
    assert cadence.budget_par_minute == DA.PLAFOND_RATTRAPAGE_PAR_MINUTE
    assert any(m == DA.MOTIF_PLAFOND for _v, m in cadence.historique)


def test_une_pause_n_est_jamais_nulle_pour_un_poids_reel():
    assert DA.pause_pour_poids(20.0, budget_par_minute=600.0) > 0.0
    assert DA.pause_pour_poids(0.0, budget_par_minute=600.0) == 0.0


def test_un_budget_absurde_retombe_sur_le_plancher_au_lieu_de_ne_plus_attendre():
    """Un budget nul ne veut pas dire « pas d'attente » : ca n'a aucun sens physique, et c'est
    exactement ce qui fait bannir une IP."""
    for absurde in (0.0, -5.0, float("nan")):
        pause = DA.pause_pour_poids(100.0, budget_par_minute=absurde)
        assert pause == pytest.approx(100.0 / DA.PLANCHER_RATTRAPAGE_PAR_MINUTE * 60.0)


def test_un_reglage_incoherent_garde_l_ordre_plancher_plafond():
    cadence = DA.CadenceAimd(plancher=300.0, plafond=100.0)
    assert cadence.plafond >= cadence.plancher
    assert cadence.budget_par_minute == 300.0


def test_l_historique_dit_ce_qui_a_bouge_et_pourquoi():
    cadence = DA.CadenceAimd(succes_avant_montee=1)
    cadence.succes()
    cadence.refus()
    motifs = [m for _v, m in cadence.historique]
    assert motifs[0] == DA.MOTIF_DEMARRAGE
    assert DA.MOTIF_MONTEE in motifs and DA.MOTIF_DESCENTE in motifs
    assert "refus" in cadence.resume()
