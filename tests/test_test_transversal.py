"""Le noyau de R7/R8/R9 : UNE hypothese a travers N observations, jamais N hypotheses.

La campagne suit 209 leaders. Poser « ce leader est-il rentable ? » 209 fois = 209 essais, une
multiplicite ecrasante, et la certitude de ne rien prouver. Poser « la part agressive predit-elle
la copiabilite ? » = UNE hypothese sur 209 observations : la section transversale devient une
force. Meme logique que le carry cross-sectionnel, seul edge encore vivant ici (PBO 0,81).

Ces tests verrouillent les trois refus et la multiplicite portee.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pytest  # noqa: E402

from hl_observer.backtesting import test_transversal as T  # noqa: E402


def _obs(paires, a="style", b="pnl"):
    return [{a: x, b: y} for x, y in paires]


# ------------------------------------------------------------------ la correlation

def test_relation_croissante_parfaite():
    assert T.correlation_de_rang([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_relation_decroissante_parfaite():
    assert T.correlation_de_rang([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_les_ex_aequo_partagent_leur_rang():
    """Sinon on inventerait un ordre la ou il n'y en a pas."""
    assert T.correlation_de_rang([1, 1, 2, 2], [1, 1, 2, 2]) == pytest.approx(1.0)


def test_une_constante_ne_PREDIT_rien():
    assert T.correlation_de_rang([5, 5, 5, 5], [1, 2, 3, 4]) is None


# ------------------------------------------------------------------ les trois refus

def test_trop_peu_d_observations_est_NON_MESURABLE_et_pas_absence_de_lien():
    """LE refus qui compte : « aucun lien » sur 5 leaders est une affirmation indefendable."""
    r = T.tester(_obs([(1, 1), (2, 2), (3, 3)]), caracteristique="style", cible="pnl", essais=1)
    assert r["verdict"] == T.NON_MESURABLE and r["motif"] == T.TROP_PEU
    assert "PAS" in r["lecture"] and r["rho"] is None


def test_une_caracteristique_constante_est_NON_MESURABLE():
    r = T.tester(_obs([(7, i) for i in range(30)]), caracteristique="style", cible="pnl",
                 essais=1)
    assert r["verdict"] == T.NON_MESURABLE and r["motif"] == T.SANS_VARIATION


def test_les_observations_incompletes_sont_ECARTEES_et_comptees():
    """Imputer une moyenne, c'est inventer une observation qui n'existe pas."""
    obs = _obs([(i, i) for i in range(25)]) + [{"style": None, "pnl": 1.0},
                                               {"style": 2.0}, "pas un dict"]
    r = T.tester(obs, caracteristique="style", cible="pnl", essais=1)
    assert r["n"] == 25 and r["incompletes"] == 3


# ------------------------------------------------------------------ la multiplicite

def test_le_seuil_est_DIVISE_par_le_nombre_d_essais():
    obs = _obs([(i, i) for i in range(30)])
    un = T.tester(obs, caracteristique="style", cible="pnl", essais=1)
    cent = T.tester(obs, caracteristique="style", cible="pnl", essais=100)
    assert cent["seuil_corrige"] == un["seuil_corrige"] / 100.0


def test_un_lien_FAIBLE_ne_survit_pas_a_la_multiplicite():
    """Tester 4 caracteristiques et ne publier que la meilleure sans le dire est la facon la plus
    commune de fabriquer un faux resultat. Ici la penalite est portee, donc visible."""
    import random
    rng = random.Random(11)
    obs = [{"style": rng.random(), "pnl": rng.random()} for _ in range(40)]
    r = T.tester(obs, caracteristique="style", cible="pnl", essais=50)
    assert r["verdict"] == T.MESURE
    assert r["significatif"] is False
    assert "NON retenu" in r["lecture"]


def test_un_lien_FORT_survit_et_est_annonce_comme_tel():
    obs = _obs([(i, i * 2 + (i % 3)) for i in range(40)])
    r = T.tester(obs, caracteristique="style", cible="pnl", essais=4)
    assert r["significatif"] is True and "LIEN RETENU" in r["lecture"]
    assert r["rho"] > 0.9


def test_la_lecture_porte_TOUJOURS_son_denominateur_et_ses_essais():
    obs = _obs([(i, -i) for i in range(30)])
    lecture = T.tester(obs, caracteristique="style", cible="pnl", essais=7)["lecture"]
    assert "30 observations" in lecture and "7 essai" in lecture


# ------------------------------------------------------------------ comparaison de groupes (R7, R8)

def test_un_groupe_trop_petit_est_NOMME_non_mesurable_et_pas_mauvais():
    """LE piege du decoupage par regime : 6 jours en quatre regimes donnent des groupes ou l'on
    ne peut rien conclure. Les traiter comme des resultats fabrique un faux PROVEN."""
    obs = ([{"regime": "TENDANCE", "pnl": 1.0}] * 12
           + [{"regime": "CRISE", "pnl": 9.0}] * 2)
    r = T.comparer_groupes(obs, groupe="regime", valeur="pnl", essais=1)
    assert r["groupes"]["CRISE"]["verdict"] == T.NON_MESURABLE
    assert r["groupes"]["CRISE"]["motif"] == T.TROP_PEU
    assert "CRISE" not in r["mesurables"]


def test_un_seul_groupe_mesurable_n_est_PAS_une_egalite():
    obs = [{"regime": "TENDANCE", "pnl": 1.0}] * 12 + [{"regime": "CRISE", "pnl": 9.0}]
    r = T.comparer_groupes(obs, groupe="regime", valeur="pnl", essais=1)
    assert r["verdict"] == T.NON_MESURABLE and "PAS une egalite" in r["lecture"]


def test_l_ecart_porte_TOUJOURS_les_effectifs():
    obs = ([{"g": "VISIBLE", "cout": 1.0}] * 15 + [{"g": "CACHE", "cout": 3.0}] * 15)
    r = T.comparer_groupes(obs, groupe="g", valeur="cout", essais=1)
    assert r["verdict"] == T.MESURE
    assert r["meilleur"] == "CACHE" and r["pire"] == "VISIBLE"
    assert "n=15" in r["lecture"]
    assert r["ecart"] == 2.0
