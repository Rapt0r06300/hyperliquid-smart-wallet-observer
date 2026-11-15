"""AVANT « est-ce rentable ? » : est-ce PLACABLE, et est-ce SURVIVABLE ?

Tout l'appareil de ce labo repondait a « cet edge survit-il aux couts ? ». Aucune ligne ne
repondait a « cet ordre serait-il accepte, et la position tiendrait-elle ? ». La recherche le dit
en une phrase : **« delta-neutre n'est pas a l'abri d'une liquidation »**, avec des excursions
adverses mesurees de **+116 % (BTC) a +400 % (SOL)** sur 31 a 98 jours de detention.

Ces tests verrouillent les contraintes DURES publiees par la venue (notionnel minimum 10 USD,
mmr = moitie de la marge initiale au levier max, formule exacte du prix de liquidation, marge de
maintenance non rendue en liquidation de secours) et le calcul qui en decoule.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import survie_position as S  # noqa: E402


# ------------------------------------------------------- le taux de maintenance de la venue

@pytest.mark.parametrize("levier_max, attendu", [
    (40, 0.0125),    # BTC : 1,25 %, la borne BASSE publiee
    (25, 0.02),      # ETH
    (20, 0.025),     # SOL, XRP
    (10, 0.05),      # la plupart des altcoins
    (3, 1 / 6),      # 16,7 %, la borne HAUTE publiee
])
def test_le_taux_de_maintenance_suit_la_formule_de_la_venue(levier_max, attendu):
    """« la marge de maintenance est la moitie de la marge initiale au levier maximum »,
    soit de 1,25 % (40x) a 16,7 % (3x)."""
    assert S.taux_de_maintenance(levier_max) == pytest.approx(attendu)


# ------------------------------------------------------- le notionnel minimum

def test_un_ordre_sous_10_USD_est_REJETE_et_pas_appele_petite_position():
    """A 350 USD de capital, le minimum de la venue est une contrainte VIVANTE. Une regle de
    dimensionnement qui sort 4 USD ne produit pas une petite position : aucune position."""
    r = S.ordre_placable(notionnel_usd=4.0)
    assert r["verdict"] == S.REJETE
    assert r["motif"] == S.SOUS_LE_MINIMUM
    assert "aucune position" in r["lecture"]
    assert S.ordre_placable(notionnel_usd=10.0)["verdict"] == S.PLACABLE


# ------------------------------------------------------- la formule de liquidation

def test_un_long_a_1x_n_est_PAS_liquidable():
    """Verification de la formule de la venue sur le cas ou la reponse est connue : a 1x en
    cross, toute la perte est couverte par le capital, le prix de liquidation tombe a zero."""
    capital, prix = 1000.0, 100.0
    taille = capital / prix                      # notionnel = capital => levier 1x
    mmr = S.taux_de_maintenance(10)              # 5 %
    marge = capital - mmr * capital
    liq = S.prix_de_liquidation(prix=prix, sens=S.LONG, taille=taille,
                                marge_disponible=marge, levier_maintenance=1 / mmr)
    assert liq == pytest.approx(0.0, abs=1e-9)


def test_un_long_a_5x_se_liquide_vers_moins_16_pourcent():
    capital, prix, levier = 1000.0, 100.0, 5.0
    notionnel = capital * levier
    taille = notionnel / prix
    mmr = S.taux_de_maintenance(10)
    marge = capital - mmr * notionnel
    liq = S.prix_de_liquidation(prix=prix, sens=S.LONG, taille=taille,
                                marge_disponible=marge, levier_maintenance=1 / mmr)
    assert (liq - prix) / prix == pytest.approx(-0.1579, abs=0.001)


def test_un_sens_inconnu_ne_rend_pas_un_prix():
    assert S.prix_de_liquidation(prix=100, sens=0, taille=1, marge_disponible=10,
                                 levier_maintenance=20) is None


# ------------------------------------------------------- LE calcul qui change le dimensionnement

def test_les_400_pourcent_mesures_sur_SOL_imposent_un_levier_sous_UN_QUART():
    """L'inversion de la formule de la venue : L_max = 1/(e(1+mmr)+mmr). Pour SOL (20x, mmr
    2,5 %) et l'excursion de +400 % REELLEMENT OBSERVEE, le plafond tombe a ~0,24x."""
    plafond = S.levier_maximum_survivable(excursion=4.00,
                                          taux_maintenance=S.taux_de_maintenance(20))
    assert plafond == pytest.approx(0.2424, abs=0.002)
    assert plafond < 0.25


def test_les_116_pourcent_mesures_sur_BTC_imposent_un_levier_SOUS_1x():
    """Meme sur BTC, l'actif le plus permissif de la venue (mmr 1,25 %), l'excursion observee
    interdit le levier 1x."""
    plafond = S.levier_maximum_survivable(excursion=1.16,
                                          taux_maintenance=S.taux_de_maintenance(40))
    assert plafond == pytest.approx(0.8424, abs=0.002)
    assert plafond < 1.0


def test_l_excursion_supportee_et_le_plafond_sont_coherents():
    """Une inversion correcte doit se refermer sur elle-meme."""
    mmr = S.taux_de_maintenance(20)
    plafond = S.levier_maximum_survivable(excursion=4.0, taux_maintenance=mmr)
    assert S.excursion_supportee(levier=plafond, taux_maintenance=mmr) == pytest.approx(4.0,
                                                                                        abs=1e-6)


# ------------------------------------------------------- le cout cache de la liquidation

def test_la_liquidation_de_secours_coute_la_marge_de_maintenance_EN_PLUS():
    """« During backstop liquidation, the maintenance margin is not returned to the user. »
    C'est un terme de perte que personne ne modelise."""
    assert S.cout_de_la_liquidation(notionnel_usd=1000.0,
                                    taux_maintenance=0.05) == pytest.approx(50.0)


# ------------------------------------------------------- la decision complete

def test_un_short_a_2x_sur_un_altcoin_est_NON_SURVIVABLE():
    r = S.decider(capital_usd=350.0, notionnel_usd=700.0, levier_max_venue=20,
                  excursion_adverse=4.00, sens=S.SHORT)
    assert r["verdict"] == S.NON_SURVIVABLE
    assert "NON SURVIVABLE" in r["lecture"]
    assert r["notionnel_maximum_usd"] == pytest.approx(0.2424 * 350.0, abs=1.0)


def test_sous_le_plafond_la_position_survit():
    r = S.decider(capital_usd=350.0, notionnel_usd=80.0, levier_max_venue=20,
                  excursion_adverse=4.00, sens=S.SHORT)
    assert r["verdict"] == S.SURVIVABLE


def test_un_mmr_INCONNU_est_refuse_et_pas_suppose_favorable():
    """Supposer 1,25 % (reserve a BTC) autoriserait silencieusement un levier mortel sur un alt."""
    r = S.decider(capital_usd=350.0, notionnel_usd=100.0, levier_max_venue=None,
                  excursion_adverse=4.00)
    assert r["verdict"] == S.NON_MESURABLE
    assert r["motif"] == S.MMR_INCONNU
    assert "mortel" in r["lecture"]


def test_l_ABSENCE_de_scenario_adverse_n_est_pas_un_scenario_favorable():
    r = S.decider(capital_usd=350.0, notionnel_usd=100.0, levier_max_venue=20,
                  excursion_adverse=None)
    assert r["verdict"] == S.NON_MESURABLE
    assert r["motif"] == S.EXCURSION_ABSENTE
    assert "n'est pas un scenario favorable" in r["lecture"]


def test_le_placement_est_verifie_AVANT_la_survie():
    """Un ordre rejete par la venue n'a pas de question de survie : il n'existe pas."""
    r = S.decider(capital_usd=350.0, notionnel_usd=4.0, levier_max_venue=20,
                  excursion_adverse=4.00)
    assert r["verdict"] == S.REJETE
    assert r["motif"] == S.SOUS_LE_MINIMUM
