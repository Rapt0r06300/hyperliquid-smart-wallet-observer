"""LE MOTEUR CARRY — **la seule stratégie mesurée POSITIVE du projet.**

Ces tests gardent ce qui a failli nous mentir :
  * le coût est de **23 bps** (4 exécutions, spot **+** perp) -- pas 18. *Le spot coûte 2,7x le
    perp en maker : c'est ce qui a fait sous-estimer T2b de 5 bps.*
  * l'APR se juge sur le capital des **DEUX** jambes -- *juger sur une seule, c'est doubler le
    chiffre* (la faute de T2, corrigée par T2b).
  * le funding est **HORAIRE** (HL paie a l'heure) -- pas le taux 8 h des CEX.
  * 🔴 la famille CARRY doit **franchir** le noyau, la ou COPY est refusee.
"""
from __future__ import annotations

import pytest

from hl_observer.decision_engine.noyau_unique import (
    REFUS_ZONE_MORTE,
    Contexte,
    decider,
    famille_de_la_strategie,
)
from hl_observer.signals.signal_taxonomy import (
    CARRY_STRUCTUREL,
    DISCRETIONNAIRE_PUBLIC,
    verdict_du_signal,
)
from hl_observer.strategies.carry_runtime import (
    CAPITAL_SUR_DEUX_JAMBES,
    COUT_ALLER_RETOUR_MAKER_BPS,
    COUT_ALLER_RETOUR_TAKER_BPS,
    HEURES_MAX_POUR_AMORTIR,
    MOTIF_CARRY_OUVRABLE,
    MOTIF_FUNDING_TROP_FAIBLE,
    MOTIF_PAS_DE_DONNEE,
    CandidatCarry,
    evaluer,
    selectionner,
)


# ════════════════════════════════════════════════════════════════════════════════════════════
# 1. 🔴 LE CARRY FRANCHIT LE NOYAU, LA OU LE COPY EST REFUSE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_la_famille_CARRY_n_est_PAS_une_zone_morte() -> None:
    """***Ce n'est PAS une prediction. C'est un PAIEMENT pour detenir une position.***

    C'est l'exact oppose du copy-trading, qui pariait qu'un leader savait quelque chose --
    **et la mesure a dit qu'il ne savait rien** (-7,97 bps, meme a cout ZERO).
    """
    assert famille_de_la_strategie("CARRY") == CARRY_STRUCTUREL
    assert famille_de_la_strategie("COPY") == DISCRETIONNAIRE_PUBLIC

    ok_carry, _ = verdict_du_signal(CARRY_STRUCTUREL)
    ok_copy, _ = verdict_du_signal(DISCRETIONNAIRE_PUBLIC)
    assert ok_carry, "le CARRY doit pouvoir etre CHERCHE"
    assert not ok_copy, "le COPY est une zone morte PROUVEE"


def test_le_COPY_est_refuse_par_le_noyau_a_la_porte_1() -> None:
    d = decider(Contexte(strategie="COPY", coin="BTC", direction="LONG", notional_usd=500.0))
    assert d.raison == REFUS_ZONE_MORTE
    assert not d.autorise


# ════════════════════════════════════════════════════════════════════════════════════════════
# 2. 🔴 LES COUTS REELS : 23 bps, PAS 18
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_cout_est_de_23_bps_car_le_SPOT_coute_plus_cher_que_le_PERP() -> None:
    """🔴 *Le spot coute **4,0 bps** maker (le perp 1,5). T2b avait sa jambe SPOT chiffree en
    PERP -> aller-retour 18 -> **23 bps**, soit **-15 % de son edge**.*"""
    assert COUT_ALLER_RETOUR_TAKER_BPS == pytest.approx(23.0)   # 2x4,5 (perp) + 2x7,0 (spot)
    assert COUT_ALLER_RETOUR_MAKER_BPS == pytest.approx(11.0)   # 2x1,5 + 2x4,0
    assert COUT_ALLER_RETOUR_TAKER_BPS != pytest.approx(18.0), "l'ancienne valeur, FAUSSE"


def test_l_APR_se_juge_sur_le_capital_des_DEUX_jambes() -> None:
    """*Juger sur une seule jambe, c'est DOUBLER le chiffre.* (La faute de T2, corrigee par T2b.)

    🔴 **CE TEST ENCODAIT L'ANCIEN CHIFFRE FAUX.** Il attendait le **BRUT** :
        `0,5 x 24 x 365 / 1e4`  -- ***sans les 23 bps de couts.***
    C'est precisement le bug repare le 2026-07-14 : les couts etaient verifies a la porte,
    puis **jamais soustraits du chiffre**. *Un cout qu'on verifie mais qu'on ne soustrait pas
    est un cout qu'on CACHE.*

    -> le test verifie maintenant **LES DEUX** :
       (a) la division par 2 jambes est toujours la (l'acquis de T2b) ;
       (b) **les couts sont DANS le chiffre** (l'acquis d'aujourd'hui).
    """
    c = CandidatCarry(coin="HYPE", funding_bps_h=1.0, notional_usd=500.0)
    assert CAPITAL_SUR_DEUX_JAMBES == 2.0

    # (a) le BRUT reste la reference historique : 1 bps/h -> 0,5 bps/h sur le CAPITAL
    assert c.apr_brut_sur_capital == pytest.approx(0.5 * 24 * 365 / 1e4)

    # (b) 🔑 mais le chiffre PUBLIE doit etre le NET -- strictement plus petit.
    assert c.apr_sur_capital < c.apr_brut_sur_capital, (
        "REGRESSION : l'APR publie est redevenu le BRUT. Les 23 bps ont disparu."
    )
    attendu = ((1.0 * HEURES_MAX_POUR_AMORTIR - COUT_ALLER_RETOUR_TAKER_BPS)
               / CAPITAL_SUR_DEUX_JAMBES) / 1e4 * (24 * 365 / HEURES_MAX_POUR_AMORTIR)
    assert c.apr_sur_capital == pytest.approx(attendu, rel=1e-9)


# ════════════════════════════════════════════════════════════════════════════════════════════
# 3. LA PORTE : le funding paie-t-il les 4 executions ?
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_LE_VRAI_FUNDING_DE_HYPE_EST_OUVRABLE() -> None:
    """🔴🔴 **LE TEST QUI A CORRIGE MON PROPRE GATE.**

    Mesure REELLE sur **120 jours** : HYPE = **+0,1043 bps/h -> +4,28 % APR**, et **il a du spot**.
    Mon gate le REFUSAIT (« funding trop faible ») parce qu'il exigeait d'amortir en **24 h**.

    ***UN CARRY SE TIENT. IL NE SE SCALPE PAS.*** J'avais copie l'horloge d'un scalp (#531,
    capture de funding HORAIRE) pour juger une position tenue des MOIS.
    *Le juger avec le mauvais cadran, c'est le tuer par erreur.*
    """
    v = evaluer(CandidatCarry(coin="HYPE", funding_bps_h=0.1043, notional_usd=500.0))
    assert v.ouvrable, "🔴 le SEUL trade valable du projet doit franchir la porte"
    assert v.motif == MOTIF_CARRY_OUVRABLE
    # 23 bps / 0,1043 = ~220 h = ~9 jours. C'est NORMAL pour un carry.
    assert v.heures_pour_amortir == pytest.approx(23.0 / 0.1043, abs=1.0)
    assert 200 < v.heures_pour_amortir < 240

    # 🔴 **L'ANCIENNE ATTENTE (~4,6 %) ETAIT LE BRUT.** Le NET, apres les 23 bps de couts
    #    amortis sur 30 jours, vaut **~3,2 %**. *Le vrai chiffre est plus petit. C'est le vrai.*
    #    -> a ce niveau, HYPE reste au-dessus du benchmark HLP (mesure a ~0 % APR), mais il
    #       n'a plus rien de spectaculaire. **On ne maquille pas.**
    assert v.apr_sur_capital == pytest.approx(0.0317, abs=0.003)   # NET, pas brut
    assert v.apr_sur_capital < 0.0457, "l'ancien chiffre etait le BRUT : les couts manquaient"


def test_un_funding_VRAIMENT_nul_ne_paie_toujours_PAS() -> None:
    """SOL : -0,005 bps/h. Meme sur 30 jours, ca ne paie rien."""
    v = evaluer(CandidatCarry(coin="SOL", funding_bps_h=0.005, notional_usd=500.0))
    assert not v.ouvrable and v.motif == MOTIF_FUNDING_TROP_FAIBLE


def test_un_funding_ELEVE_est_ouvrable_MAIS_avec_ses_reserves() -> None:
    v = evaluer(CandidatCarry(coin="HYPE", funding_bps_h=1.5, notional_usd=500.0))
    assert v.ouvrable and v.motif == MOTIF_CARRY_OUVRABLE
    assert v.heures_pour_amortir is not None and v.heures_pour_amortir < 24.0
    assert "ce n'est pas une promesse" in v.note.lower()
    d = v.as_dict()
    assert "UN SEUL MARCHÉ" in d["avertissement"]
    assert "HLP" in d["avertissement"], "il DOIT battre un depot passif"
    assert d["real_execution"] is False


def test_un_funding_NON_MESURE_ne_devient_PAS_un_zero() -> None:
    """*Etat vide honnete, jamais un 0 suppose.*"""
    v = evaluer(CandidatCarry(coin="X", funding_bps_h=0.0, notional_usd=500.0))
    assert not v.ouvrable and v.motif == MOTIF_PAS_DE_DONNEE


def test_le_signe_du_funding_ne_compte_pas_on_encaisse_dans_les_DEUX_sens() -> None:
    """Funding negatif -> on inverse les jambes et on encaisse quand meme."""
    v = evaluer(CandidatCarry(coin="X", funding_bps_h=-1.5, notional_usd=500.0))
    assert v.ouvrable


def test_la_selection_classe_par_APR_sur_le_CAPITAL() -> None:
    """*Moins de trades, beaucoup plus propres.*"""
    vs = selectionner([
        CandidatCarry("A", 0.01, 500.0),     # sous le seuil (0,05) -> ECARTE
        CandidatCarry("B", 1.0, 500.0),
        CandidatCarry("C", 2.0, 500.0),
    ])
    assert [v.coin for v in vs] == ["C", "B"], "A est sous le seuil : il ne doit PAS passer"
    assert all(v.ouvrable for v in vs)
