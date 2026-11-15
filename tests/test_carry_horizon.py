"""« Puis-je tenir assez longtemps pour payer le trade ? » — la question d'un trader senior.

Tout ce que ce labo a mesure meurt dans les couts : fast_follow rejete a tous les horizons
<= 300 s MEME A SPREAD NUL (donc tue par les FRAIS), DeepLOB -4 242 bps, maker naif -3,42 bp.
Le seul edge vivant est le carry de funding, et la litterature dit pourquoi on le rate :

* ce n'est pas le taux qui decide mais la DUREE (N* = C/mu : 0,38 % a 0,01 %/8 h = 12,7 jours) ;
* N* est exactement le point ou P(profit) = 50 % — un PILE OU FACE, jamais une cible ;
* mesure sur deux ans : la regle a seuil produit le PLUS de brut de toutes les regles testees et
  finit a -9 % a -15 % net (l'execution consomme 3x le brut) ; la regle qui ne trade presque pas
  (1 a 5 allers-retours en DEUX ANS) rend +2,7 % a +5,4 % net.

Ces tests verrouillent les refus qui empechent d'entrer dans un trade qu'on ne pourra pas tenir.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import carry_horizon as H  # noqa: E402


# ------------------------------------------------------------------ le seuil naif

def test_le_seuil_naif_reproduit_le_chiffre_publie():
    """0,38 % d'aller-retour a 0,01 % par 8 h = 38 periodes = 12,7 jours."""
    assert H.intervalles_pour_rentrer(0.0038, 0.0001) == pytest.approx(38.0)


def test_un_taux_NUL_ou_CONTRAIRE_ne_rend_pas_un_grand_nombre():
    """Renvoyer 10 000 intervalles laisserait croire qu'il suffit d'attendre. Aucune duree ne
    corrige un signe."""
    assert H.intervalles_pour_rentrer(0.0038, 0.0) is None
    assert H.intervalles_pour_rentrer(0.0038, -0.0001) is None


# ------------------------------------------------------------------ le seuil a 95 %

def test_le_seuil_a_95_pourcent_est_bien_PLUS_LONG_que_le_naif():
    """Le chiffre que tout le monde calcule vaut P(profit) = 50 %. Les calculateurs ne le disent
    jamais a voix haute."""
    naif = H.intervalles_pour_rentrer(0.0010, 0.0001)
    sur = H.intervalles_confiance_95(cout_aller_retour=0.0010, moyenne=0.0001,
                                     ecart_type=0.0003)
    assert naif == pytest.approx(10.0)
    assert sur > naif * 3.5            # publie : ~4,2x
    assert sur == pytest.approx(42.0, rel=0.1)


def test_la_PERSISTANCE_allonge_encore_la_duree():
    """Le funding ne se reinitialise pas entre reglements. phi = 0,3, persistance FAIBLE, suffit a
    multiplier la variance de long terme par 1,86 — publie : 64 periodes contre 42."""
    sans = H.intervalles_confiance_95(cout_aller_retour=0.0010, moyenne=0.0001,
                                      ecart_type=0.0003, persistance=0.0)
    avec = H.intervalles_confiance_95(cout_aller_retour=0.0010, moyenne=0.0001,
                                      ecart_type=0.0003, persistance=0.3)
    assert avec > sans * 1.3
    assert avec == pytest.approx(64.0, rel=0.15)


def test_une_persistance_hors_domaine_est_refusee():
    assert H.intervalles_confiance_95(cout_aller_retour=0.001, moyenne=0.0001,
                                      ecart_type=0.0003, persistance=1.0) is None


# ------------------------------------------------------------------ le taux minimal

def test_le_taux_minimal_depend_de_CE_QU_ON_PEUT_TENIR():
    """« Une APR elevee sur une ligne qu'on ne peut tenir que deux jours, au tarif taker, est
    souvent une perte. »"""
    assert H.taux_minimal(0.0026, 15) == pytest.approx(0.0026 / 15)
    # publie : 0,26 % sur 15 intervalles -> 0,0173 % par 8 h
    assert H.taux_minimal(0.0026, 15) == pytest.approx(0.000173, rel=5e-3)
    assert H.taux_minimal(0.0026, 0) is None


# ------------------------------------------------------------------ la decision

def test_on_REFUSE_un_trade_qu_on_ne_pourra_pas_tenir():
    """LE refus qui compte : entrer sans pouvoir tenir, c'est payer les frais sans encaisser le
    carry — exactement la regle a seuil qui fait le plus de brut et finit a -9 % a -15 % net."""
    r = H.decider(cout_aller_retour=0.0010, moyenne=0.0001, ecart_type=0.0003,
                  intervalles_disponibles=20, persistance=0.3)
    assert r["verdict"] == H.NON_TENABLE
    assert r["motif"] == H.HORIZON_TROP_COURT
    assert "payer les frais sans encaisser" in r["lecture"]


def test_on_accepte_quand_l_horizon_couvre_le_seuil_a_95_pourcent():
    r = H.decider(cout_aller_retour=0.0010, moyenne=0.0001, ecart_type=0.0003,
                  intervalles_disponibles=200, persistance=0.3)
    assert r["verdict"] == H.TENABLE
    assert r["facteur"] > 3.0


def test_une_volatilite_INCONNUE_n_autorise_PAS_le_seuil_naif():
    """Se rabattre sur le seuil naif dirait « confiant » la ou l'on est a pile ou face."""
    r = H.decider(cout_aller_retour=0.0010, moyenne=0.0001, ecart_type=None,
                  intervalles_disponibles=1000)
    assert r["verdict"] == H.NON_MESURABLE
    assert r["motif"] == H.VOLATILITE_INCONNUE
    assert "PILE OU FACE" in r["lecture"]


def test_un_signe_contraire_est_refuse_avant_tout_calcul_de_duree():
    r = H.decider(cout_aller_retour=0.0010, moyenne=-0.0001, ecart_type=0.0003,
                  intervalles_disponibles=10_000)
    assert r["verdict"] == H.NON_MESURABLE
    assert r["motif"] == H.TAUX_NUL_OU_CONTRAIRE
    assert "Attendre ne corrige pas un signe" in r["lecture"]
