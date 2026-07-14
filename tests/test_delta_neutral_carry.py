"""LE CARRY DELTA-NEUTRE — la voie de reouverture (2026-07-12).

    LONG spot + SHORT perp  ->  le prix s'annule. Il ne reste que le funding.

C'est la SEULE issue que la zone morte `FUNDING_JAMBE_NUE` designe elle-meme :
« une VRAIE jambe de couverture (spot ou perp oppose) qui annule le risque de prix ».

Le funding est le seul signal de ce projet qui ait une structure reelle (autocorrelation +0,70
a 1 h). Ce qui le tuait, c'etait la jambe NUE : 1 bps encaisse pour 281 bps de bruit subi.

MAIS COUVRIR N'EST PAS GRATUIT :
  * DEUX jambes = DEUX allers-retours = 6 bps en maker (4 x 1,5), 18 bps en taker ;
  * la BASE (perp - spot) se paie a l'entree si elle joue contre nous ;
  * le spot Hyperliquid est MINCE : un carry qu'on ne peut pas monter n'existe pas ;
  * et le funding S'EVAPORE (persistance 0,70/h).

Aucun ordre reel.
"""
from __future__ import annotations

import pytest


# ============================================================ LE SPREAD ETAIT ABSENT DU COUT
#
# TROUVE PAR T2 EN MESURANT LES VRAIS CARNETS (2026-07-12).
#
# Le modele comptait 6 bps (4 x maker) et **rien d'autre**. Il ignorait le SPREAD -- qui est le
# poste DOMINANT sur les carnets spot d'Hyperliquid :
#
#     HYPE   spot  0,1 bps + perp  0,1 bps  ->  le spread ne coute presque rien
#     PURR   spot 45,8 bps + perp 39,8 bps  ->  86 bps de spread contre 18 de frais (5x !)
#
# PURR encaissait +58,6 bps de funding dans son pire mois -- et payait 107 bps pour entrer et
# sortir. Le modele sans spread le declarait VIABLE. Il etait PERDANT.
#
# Un carry juge sur les frais seuls est un carry juge sur son plus petit poste de depense.

def test_le_spread_est_compte_dans_le_cout():
    """Sans spread, on sous-estime le cout d'un facteur 5 sur les carnets minces."""
    sans = cout_aller_retour_bps(0.0, 0.0, maker=False)
    avec = cout_aller_retour_bps(45.8, 39.8, maker=False)   # les vrais spreads de PURR
    assert sans == pytest.approx(COUT_TAKER_2_JAMBES_BPS)
    assert avec == pytest.approx(COUT_TAKER_2_JAMBES_BPS + 85.6), (
        "le spread des DEUX carnets doit s'ajouter aux frais : on traverse les deux, "
        "a l'entree ET a la sortie"
    )
    assert avec > sans * 4, (
        "sur PURR le spread coute 5x les frais. Un modele qui l'ignore declare VIABLE "
        "un carry PERDANT."
    )


def test_un_carnet_serre_ne_coute_presque_que_les_frais():
    """Symetrie : sur HYPE (spreads ~0,1 bps), le cout doit rester proche des frais purs."""
    c = cout_aller_retour_bps(0.1, 0.1, maker=False)
    assert c == pytest.approx(COUT_TAKER_2_JAMBES_BPS + 0.2, abs=0.01)


def test_le_mode_maker_est_une_BORNE_pas_un_plan():
    """En maker on ENCAISSE les demi-spreads -- mais seulement SI on est rempli.
    T1 a mesure ce que vaut cette hypothese : 0,33 % du flux atteignait le fond de la file.
    Le mode maker doit donc etre STRICTEMENT plus optimiste que le taker, et rester une borne."""
    m = cout_aller_retour_bps(20.0, 20.0, maker=True)
    t = cout_aller_retour_bps(20.0, 20.0, maker=False)
    assert m < t, "le maker doit etre la borne OPTIMISTE"
    assert m == pytest.approx(COUT_MAKER_2_JAMBES_BPS - 40.0)


def test_un_spread_negatif_ne_devient_pas_un_cadeau():
    """Un spread negatif n'existe pas. S'il arrive (donnee cassee), il ne doit pas
    REDUIRE le cout -- sinon une donnee corrompue fabrique un edge."""
    assert cout_aller_retour_bps(-50.0, -50.0, maker=False) == pytest.approx(
        COUT_TAKER_2_JAMBES_BPS
    )

from hl_observer.funding.delta_neutral_carry import (
    COUT_MAKER_2_JAMBES_BPS,
    COUT_TAKER_2_JAMBES_BPS,
    LIQUIDITE_SPOT_MIN_USD,
    MOTIF_BASE_TROP_CHERE,
    MOTIF_FUNDING_TROP_FAIBLE,
    MOTIF_INCONNU,
    MOTIF_PAS_DE_SPOT,
    cout_aller_retour_bps,
    MOTIF_SPOT_ILLIQUIDE,
    PERSISTANCE_1H,
    PLANCHER_PROTOCOLAIRE_BPS_H,
    evaluer_carry_neutre,
    funding_cumule_bps,
)
from hl_observer.funding.carry_liquidation_risk import (
    MOTIF_DONNEE_MANQUANTE as MOTIF_LIQ_MANQUANT,
)
from hl_observer.funding.carry_liquidation_risk import (
    MOTIF_LIQUIDE_PAR_LE_PASSE as MOTIF_LIQ_TUE,
)
from hl_observer.funding.carry_liquidation_risk import (
    fraction_marge_maintenance,
    marge_requise_pour_survivre,
)

# 🔴 T2b / #588 -- LES TROIS ENTREES DU RISQUE DE LIQUIDATION, sans lesquelles un carry est refuse.
# Mesure REELLE : HYPE, levier max 10x (maintenance 5 %), pire hausse subie sur 30 jours de
# detention = +95,6 % (4 801 bougies horaires, 200 jours).
#
# 🚩 ET UNE LECON, PAYEE PAR DEUX TESTS ROUGES : ma 1re version ecrivait `marge_ratio = 1.05`,
# recopie depuis mon propre rapport... qui AFFICHAIT « 105 % » en arrondissant a l'entier. La vraie
# marge requise est **105,38 %**. A 1,05, la jambe est liquidee a +95,24 % -- juste EN DESSOUS des
# +95,6 % reellement subis. *L'arrondi d'un rapport etait devenu l'entree d'un test.*
# D'ou : plus aucun nombre magique. Le test CALCULE la marge, il ne la recopie pas.
PIRE_HAUSSE_HYPE_30J = 0.956
LEVIER_MAX_HYPE = 10.0
RISQUE_SURVIVABLE = {
    "levier_max": LEVIER_MAX_HYPE,
    "marge_ratio": marge_requise_pour_survivre(
        PIRE_HAUSSE_HYPE_30J, fraction_marge_maintenance(LEVIER_MAX_HYPE)
    ),
    "pire_hausse_observee": PIRE_HAUSSE_HYPE_30J,
}


# ------------------------------------------------------------------ le cout de la couverture

def test_covering_costs_TWO_round_trips_not_one():
    """LE POINT QU'ON OUBLIE. Couvrir, c'est deux marches. Donc QUATRE allers-retours de frais."""
    assert COUT_MAKER_2_JAMBES_BPS == 6.0        # 4 x 1,5 bps
    assert COUT_TAKER_2_JAMBES_BPS == 18.0       # 4 x 4,5 bps


def test_the_PROTOCOL_FLOOR_never_decays_and_that_changes_EVERYTHING():
    """MON PREMIER MODELE ETAIT FAUX, ET TROP PESSIMISTE.

    Je faisais decroitre TOUT le funding vers zero -> la somme plafonnait a 3,33 x f
    -> d'ou un seuil "impossible" de 1,8 bps/h.

    La formule officielle : F = premium + clamp(interest - premium, +-0,0005), avec
    `interest` FIXE par le protocole a 0,01 %/8 h = 0,125 bps/h. La doc ecrit : "11,6 % APR
    paid to short". Et 57,2 %% de nos 105 096 releves sont EXACTEMENT a cette valeur.

    Le plancher ne meurt pas. Le carry S'ACCUMULE, lineairement, sans fin."""
    assert PLANCHER_PROTOCOLAIRE_BPS_H == 0.125

    # au plancher pur : accumulation LINEAIRE, jamais bornee
    assert funding_cumule_bps(48, 0.125) == pytest.approx(6.0)
    assert funding_cumule_bps(720, 0.125) == pytest.approx(90.0)
    # 10x plus de temps -> ~10x plus de carry. C'est ca, un plancher permanent.
    assert funding_cumule_bps(7200, 0.125) > 800


def test_the_PREMIUM_above_the_floor_DOES_decay():
    """Le premium (l'exces au-dessus du plancher) s'eteint bien, lui : persistance 0,70/h."""
    # a 5 bps/h : plancher 0,125 + premium 4,875 qui s'evapore
    court = funding_cumule_bps(3, 5.0)
    # le premium apporte au plus 4,875/(1-0,70) = 16,25 bps, puis plus rien
    assert funding_cumule_bps(10_000, 5.0) < 0.125 * 10_000 + 17.0
    assert court > 5.0


# ------------------------------------------------------------------ ce qui tue le carry

def test_WITHOUT_a_spot_market_there_is_NO_hedge_and_we_fall_back_into_the_dead_zone():
    """LE TEST QUI COMPTE. Sans spot, la couverture est impossible -> on retombe sur la jambe
    nue, qui est une ZONE MORTE (281 bps de prix pour 1 bps de funding)."""
    v = evaluer_carry_neutre(coin="X", funding_bps_h=5.0, base_bps=0.0, liquidite_spot_usd=0.0)
    assert v.viable is False
    assert v.motif == MOTIF_PAS_DE_SPOT
    assert "jambe nue" in v.note


def test_a_spot_market_TOO_THIN_to_build_the_leg_kills_the_carry():
    """Un carry qu'on ne peut pas CONSTRUIRE n'existe pas."""
    v = evaluer_carry_neutre(coin="X", funding_bps_h=5.0, base_bps=0.0,
                             liquidite_spot_usd=LIQUIDITE_SPOT_MIN_USD - 1)
    assert v.viable is False
    assert v.motif == MOTIF_SPOT_ILLIQUIDE


def test_the_BASIS_is_paid_at_entry_and_can_eat_the_whole_carry():
    """Si le perp cote 30 bps SOUS le spot, on achete cher et on vend bas : -30 bps a l'entree.
    Un funding de 0,125 bps/h met une eternite a rembourser ca."""
    v = evaluer_carry_neutre(coin="X", funding_bps_h=0.125, base_bps=-30.0,
                             liquidite_spot_usd=100_000.0)
    assert v.cout_entree_bps == pytest.approx(6.0 + 30.0)
    # 36 bps a rembourser a 0,125 bps/h -> 288 heures = 12 JOURS avant le premier centime.
    # Le carry n'est pas impossible : il est LENT. Et sur 24 h, il est NEGATIF.
    # 36 bps a rembourser a 0,125 bps/h -> 288 heures = 12 JOURS avant le premier centime.
    assert v.heures_pour_rentabiliser is not None and v.heures_pour_rentabiliser > 240


def test_a_FAVOURABLE_basis_pays_us_at_entry():
    """Base POSITIVE = le perp est plus cher = on le short HAUT. La base joue POUR nous."""
    v = evaluer_carry_neutre(coin="X", funding_bps_h=1.0, base_bps=+10.0,
                             liquidite_spot_usd=100_000.0)
    assert v.cout_entree_bps == pytest.approx(6.0 - 10.0)   # negatif : on est PAYE pour entrer


def test_a_NEGATIVE_funding_means_shorting_the_perp_PAYS_instead_of_earning():
    v = evaluer_carry_neutre(coin="X", funding_bps_h=-2.0, base_bps=0.0,
                             liquidite_spot_usd=100_000.0)
    assert v.viable is False
    assert v.motif == MOTIF_FUNDING_TROP_FAIBLE


def test_the_MEDIAN_funding_DOES_repay_the_two_legs_in_48_hours():
    """LE RENVERSEMENT. Avec le plancher permanent, le funding MEDIAN (0,125 bps/h) rembourse
    les 6 bps des deux jambes en 48 heures -- puis c'est du portage pur.

    Il n'y a plus de SEUIL de funding. Il y a un DELAI. Ce n'est pas la meme chose du tout."""
    assert funding_cumule_bps(48, 0.125) == pytest.approx(COUT_MAKER_2_JAMBES_BPS)
    v = evaluer_carry_neutre(coin="MEDIAN", funding_bps_h=0.125, base_bps=0.0,
                             liquidite_spot_usd=100_000.0, **RISQUE_SURVIVABLE)
    assert v.viable is True
    assert v.heures_pour_rentabiliser == 48.0
    # 🔴 T2b : le gain PUBLIE est desormais celui du CAPITAL TOTAL (spot cash + marge du perp).
    # Sur le notionnel seul on lisait ~84 bps ; avec m = 1,05 le capital double, et le vrai
    # rendement tombe a ~41 bps. Le carry ne disparait pas -- il est DEUX FOIS plus petit.
    assert v.gain_net_24h_bps is not None and 35 < v.gain_net_24h_bps < 50
    # 10,95 % d'APR delta-neutre : ce que la doc Hyperliquid annonce ("11,6 % to short")
    apr = 0.125 * 24 * 365 / 100
    assert 10.0 < apr < 12.0


# ------------------------------------------------------------------ et ce qui le rend viable

def test_a_HIGH_and_PERSISTENT_funding_with_a_liquid_spot_IS_viable():
    """On ne refuse pas par principe. Un funding fort, un spot liquide, une base neutre,
    ET une jambe perp qui survit au pire mouvement observe : le carry paie."""
    v = evaluer_carry_neutre(coin="BON", funding_bps_h=8.0, base_bps=0.0,
                             liquidite_spot_usd=200_000.0, **RISQUE_SURVIVABLE)
    assert v.viable is True
    assert v.heures_pour_rentabiliser is not None and v.heures_pour_rentabiliser <= 2
    assert v.gain_net_24h_bps is not None and v.gain_net_24h_bps > 0


# ------------------------------------------------ 🔴 T2b / #588 : LE VERROU DE LIQUIDATION

def test_UN_CARRY_SANS_SON_RISQUE_DE_LIQUIDATION_EST_REFUSE():
    """🔴 LE VERROU. Sans levier max, sans marge, sans pire mouvement observe : NO_TRADE.

    Ces trois tests declaraient un carry « viable » alors que sa jambe perp n'avait JAMAIS ete
    evaluee. *Un carry evalue sans son risque de liquidation est un carry evalue sur ses BONNES
    nouvelles.*
    """
    v = evaluer_carry_neutre(coin="BON", funding_bps_h=8.0, base_bps=0.0,
                             liquidite_spot_usd=200_000.0)     # <- sans les 3 entrees du risque
    assert v.viable is False
    assert v.motif == MOTIF_LIQ_MANQUANT


def test_UNE_MARGE_TROP_FINE_FAIT_TOMBER_UN_CARRY_PAR_AILLEURS_PARFAIT():
    """Funding fort, spot profond, base neutre... et une marge de 15 % : liquide a +9,5 %.
    Le prix HYPE a REELLEMENT monte de +95,6 % sur 30 jours. Le carry meurt."""
    v = evaluer_carry_neutre(coin="HYPE", funding_bps_h=8.0, base_bps=0.0,
                             liquidite_spot_usd=200_000.0,
                             levier_max=10.0, marge_ratio=0.15, pire_hausse_observee=0.956)
    assert v.viable is False
    assert v.motif == MOTIF_LIQ_TUE
    assert "FUNDING_JAMBE_NUE" in v.note


def test_maker_execution_more_than_halves_the_cost_of_covering():
    """18 bps en taker contre 6 en maker. Sur un carry, l'execution N'EST PAS un detail."""
    taker = evaluer_carry_neutre(coin="X", funding_bps_h=3.0, base_bps=0.0,
                                 liquidite_spot_usd=100_000.0, maker=False)
    maker = evaluer_carry_neutre(coin="X", funding_bps_h=3.0, base_bps=0.0,
                                 liquidite_spot_usd=100_000.0, maker=True)
    assert maker.cout_entree_bps < taker.cout_entree_bps / 2.5


# ------------------------------------------------------------------ deny-by-default

def test_a_missing_measurement_is_ALWAYS_a_refusal():
    """Une jambe qu'on ne mesure pas est une jambe qu'on n'a pas."""
    for kw in ({"funding_bps_h": None}, {"base_bps": None}, {"liquidite_spot_usd": None}):
        args = {"coin": "X", "funding_bps_h": 5.0, "base_bps": 0.0,
                "liquidite_spot_usd": 100_000.0}
        args.update(kw)
        v = evaluer_carry_neutre(**args)
        assert v.viable is False
        assert v.motif == MOTIF_INCONNU


def test_the_verdict_never_claims_a_real_execution():
    v = evaluer_carry_neutre(coin="X", funding_bps_h=8.0, base_bps=0.0,
                             liquidite_spot_usd=200_000.0)
    d = v.as_dict()
    assert d["real_execution"] is False
    assert "le prix s'annule" in d["structure"]
