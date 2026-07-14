"""LE CARRY DE FUNDING, MESURE (2026-07-11) -- et pourquoi le gate historique etait un piege.

CHIFFRES REELS, 232 marches Hyperliquid, 9 512 releves :

    |funding| median .......... 0,125 bps/h
    persistance a 1 h ......... +0,70   <-- REEL. Le funding est PREVISIBLE.
    ratio funding / bruit ..... 0,0036  <-- pour 1 bps encaisse, 281 bps de mouvement subi

Le funding est le premier signal de ce projet qui a une vraie structure. Et il est quand meme
inexploitable NU. Les deux affirmations sont vraies en meme temps, et c'est tout le sujet.

Aucun ordre reel.
"""
from __future__ import annotations

from hl_observer.funding.funding_carry_economics import (
    PERSISTANCE_1H_MESUREE,
    REFUS_FUNDING_INCONNU,
    REFUS_NON_COUVERT,
    REFUS_TROP_LENT,
    evaluer_carry,
    funding_restant_apres,
    piege_du_seuil_de_funding,
)

COUT = 13.0          # aller-retour taker, frais Hyperliquid reels


# --------------------------------------------------------------- LA regle dure

def test_an_unhedged_leg_is_ALWAYS_refused_whatever_the_funding():
    """LE TEST QUI COMPTE. Meme un funding de reve ne rachete pas une jambe nue.

    Le code actuel ouvre UNE jambe et facture un `hedge_venue_extra_bps` forfaitaire qui fait
    SEMBLANT d'etre une couverture. Un frais n'est pas un hedge."""
    v = evaluer_carry(funding_bps_h=50.0, bruit_prix_bps_h=30.0,
                      cout_aller_retour_bps=COUT, couvert=False)
    assert v.viable is False
    assert v.motif == REFUS_NON_COUVERT
    assert "pari directionnel" in v.note


def test_CASHCAT_the_only_market_the_old_gate_allowed_is_the_WORST_one():
    """CASHCAT : 2,84 bps/h de funding... et 219 bps/h de mouvement de prix. C'est le SEUL marche
    que le gate a 2,5 bps/h laissait passer. Il selectionnait le plus dangereux."""
    v = evaluer_carry(funding_bps_h=2.836, bruit_prix_bps_h=219.1,
                      cout_aller_retour_bps=COUT, couvert=False)
    assert v.viable is False
    assert v.ratio < 0.02, "on encaisse 77x plus de bruit que de funding"


def test_raising_the_funding_threshold_CONCENTRATES_the_risk():
    """LE PIEGE, RENDU VISIBLE. Monter le seuil ne filtre pas le risque : il le concentre,
    parce qu'un funding eleve l'est PRECISEMENT parce que le marche est dangereux."""
    marches = {
        "BTC": (0.125, 12.0), "ETH": (0.125, 15.0), "SOL": (0.20, 25.0),
        "IOTA": (0.797, 2.3), "TRUMP": (0.663, 9.2), "CASHCAT": (2.836, 219.1),
    }
    r = piege_du_seuil_de_funding(marches)
    bruit_seuil_0 = next(l["bruit_moyen_bps_h"] for l in r["lignes"] if l["seuil_bps_h"] == 0.0)
    bruit_seuil_2_5 = next(l["bruit_moyen_bps_h"] for l in r["lignes"] if l["seuil_bps_h"] == 2.5)
    assert bruit_seuil_2_5 > bruit_seuil_0, "le seuil eleve doit exposer sa propre toxicite"
    assert "concentre" in r["avertissement"]


# --------------------------------------------------------------- le funding s'evapore

def test_the_funding_DECAYS_it_does_not_stay_put():
    """Persistance mesuree 0,70/h. Supposer qu'un funding tient 33 h, c'est se mentir."""
    assert funding_restant_apres(0, funding_initial_bps_h=1.0) == 1.0
    assert abs(funding_restant_apres(1, funding_initial_bps_h=1.0) - PERSISTANCE_1H_MESUREE) < 1e-9
    assert funding_restant_apres(24, funding_initial_bps_h=1.0) < 0.001


def test_a_hedged_carry_that_needs_too_long_to_amortize_is_still_refused():
    """Meme couvert : si les couts mettent 40 h a s'amortir, le funding aura disparu avant."""
    v = evaluer_carry(funding_bps_h=0.125, bruit_prix_bps_h=10.0,
                      cout_aller_retour_bps=COUT, couvert=True, heures_detention_max=24.0)
    assert v.viable is False
    assert v.motif == REFUS_TROP_LENT
    assert v.heures_pour_couvrir_couts is not None and v.heures_pour_couvrir_couts > 100


def test_a_hedged_and_fast_enough_carry_IS_accepted():
    """Le module ne refuse pas par principe : il refuse par arithmetique. S'il existe un carry
    couvert dont les couts s'amortissent vite, il passe."""
    v = evaluer_carry(funding_bps_h=3.0, bruit_prix_bps_h=200.0,   # bruit fort, mais COUVERT
                      cout_aller_retour_bps=COUT, couvert=True, heures_detention_max=24.0)
    assert v.viable is True
    assert v.couvert is True
    assert v.heures_pour_couvrir_couts is not None and v.heures_pour_couvrir_couts < 5


def test_hedged_means_the_price_noise_no_longer_decides():
    """Couvert, le bruit de prix ne vote plus : c'est TOUT l'interet du delta-neutre."""
    fort = evaluer_carry(funding_bps_h=3.0, bruit_prix_bps_h=500.0,
                         cout_aller_retour_bps=COUT, couvert=True)
    faible = evaluer_carry(funding_bps_h=3.0, bruit_prix_bps_h=1.0,
                           cout_aller_retour_bps=COUT, couvert=True)
    assert fort.viable is faible.viable is True


# --------------------------------------------------------------- deny-by-default

def test_an_unknown_funding_rate_NEVER_opens_a_position():
    v = evaluer_carry(funding_bps_h=None, bruit_prix_bps_h=10.0,
                      cout_aller_retour_bps=COUT, couvert=True)
    assert v.viable is False
    assert v.motif == REFUS_FUNDING_INCONNU


def test_an_unknown_volatility_NEVER_opens_a_position():
    v = evaluer_carry(funding_bps_h=1.0, bruit_prix_bps_h=None,
                      cout_aller_retour_bps=COUT, couvert=True)
    assert v.viable is False
    assert v.motif == REFUS_FUNDING_INCONNU


def test_a_zero_funding_is_never_viable():
    v = evaluer_carry(funding_bps_h=0.0, bruit_prix_bps_h=10.0,
                      cout_aller_retour_bps=COUT, couvert=True)
    assert v.viable is False


def test_the_verdict_never_claims_a_real_execution():
    v = evaluer_carry(funding_bps_h=3.0, bruit_prix_bps_h=5.0,
                      cout_aller_retour_bps=COUT, couvert=True)
    assert v.as_dict()["real_execution"] is False
