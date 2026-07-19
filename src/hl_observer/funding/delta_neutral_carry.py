"""LE CARRY DELTA-NEUTRE : SPOT LONG + PERP SHORT (2026-07-12).

    C'EST LA VOIE DE REOUVERTURE QUE LA ZONE MORTE `FUNDING_JAMBE_NUE` DESIGNE ELLE-MEME :
    « une VRAIE jambe de couverture (spot ou perp oppose) qui annule le risque de prix. »

POURQUOI CETTE FOIS C'EST DIFFERENT.

Le funding est le SEUL signal de tout ce projet qui a une structure reelle :
autocorrelation **+0,70 a une heure** (le copy-trading : rapport signal/bruit 0,03).
Il est PREVISIBLE.

Ce qui le tuait, ce n'etait pas le funding. C'etait la JAMBE NUE : on encaissait 1 bps de portage
en subissant 281 bps de bruit de prix. Un pari directionnel avec un coupon.

    LONG spot + SHORT perp, meme taille  ->  le prix s'annule.
    Il ne reste que le funding. C'est du PORTAGE, pas un pari.

C'est litteralement le "grinder" : beaucoup de mini-positions, zero risque directionnel.

CE QUI PEUT ENCORE LE TUER, ET IL FAUT LE MESURER :

  1. LA BASE (spot - perp). Si le perp cote 30 bps sous le spot, on achete cher et on vend
     bas : on paie 30 bps a l'entree. Le funding met des heures a les rembourser.
  2. LES FRAIS DES DEUX JAMBES. Deux marches, deux allers-retours. Pas un.
  3. LA LIQUIDITE DU SPOT. Le spot Hyperliquid est BEAUCOUP plus mince que le perp.
     Un carry qu'on ne peut pas monter n'existe pas.
  4. LA CONVERGENCE. A la sortie, la base peut avoir bouge CONTRE nous.

DENY-BY-DEFAULT : sans les quatre, on refuse. Un carry mal mesure est un pari deguise.

PUR, sans I/O. Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hl_observer.funding.carry_liquidation_risk import evaluer_risque_liquidation

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔴 CORRIGE LE 2026-07-13 (#543 / H-138) — LE SPOT NE COUTE PAS LE MEME PRIX QUE LE PERP.
#
# AVANT :   TAKER_BPS = 4.5 ; MAKER_BPS = 1.5 ; COUT = 4 x le meme taux.
#           -> on appliquait les frais **PERP** aux **DEUX** jambes.
#
# OR le carry est **long SPOT / short PERP**, et la doc officielle donne DEUX grilles :
#           perp : taker 4,5 bps   maker 1,5 bps
#           spot : taker **7,0** bps   maker **4,0** bps   <- 1,6x et 2,7x plus cher !
#
#   aller-retour taker :  18,0 bps modelises  ->  **23,0 bps** reels   (+5,0)
#   aller-retour maker :   6,0 bps modelises  ->  **11,0 bps** reels   (+5,0, soit **+83 %**)
#
# ***Le cout du seul resultat positif du projet (T2b, le carry HYPE) etait sous-estime de 5 bps.***
# Le carry SURVIT -- il maigrit encore. On ne maquille pas : on soustrait.
#
# Source unique de verite : hl_observer/fees/hyperliquid_fees.py (doc officielle, 2026-07-13).
# ═══════════════════════════════════════════════════════════════════════════════════════════════
from hl_observer.fees.hyperliquid_fees import nos_frais as _nos_frais

_PERP = _nos_frais("perp")
_SPOT = _nos_frais("spot")

TAKER_BPS = _PERP.taker_bps          # 4,5 -- conserve pour compatibilite (jambe PERP)
MAKER_BPS = _PERP.maker_bps          # 1,5 -- idem

TAKER_SPOT_BPS = _SPOT.taker_bps     # 7,0
MAKER_SPOT_BPS = _SPOT.maker_bps     # 4,0

# DEUX jambes (spot + perp) x DEUX passages (entree + sortie) = QUATRE executions,
# **mais deux tarifs differents**.
COUT_TAKER_2_JAMBES_BPS = 2 * TAKER_BPS + 2 * TAKER_SPOT_BPS   # 23,0 (etait 18,0)
COUT_MAKER_2_JAMBES_BPS = 2 * MAKER_BPS + 2 * MAKER_SPOT_BPS   # 11,0 (etait  6,0)


def cout_aller_retour_bps(spot_spread_bps: float, perp_spread_bps: float,
                          maker: bool = False) -> float:
    """LE COUT COMPLET du carry : frais **+ SPREAD**.

    LE TROU QUE T2 A TROUVE (2026-07-12) -- ET C'ETAIT LE COUT DOMINANT.
    ----------------------------------------------------------------------
    Le premier modele comptait 6 bps (4 x maker) et **rien d'autre**. Il ignorait le SPREAD.
    Les carnets spot d'Hyperliquid, mesures :

        HYPE   spot 6,9 bps   perp 0,1 bps   ->  le spread coute 7 bps
        PURR   spot 45,5 bps  perp 34,5 bps  ->  le spread coute 80 bps  (13x les frais !)
        STABLE spot 53,5 bps  perp 0,8 bps

    Sur PURR, le spread coute **treize fois** ce que le modele appelait "le cout". Un carry
    juge sur les frais seuls est un carry juge sur son plus petit poste de depense.

    EN TAKER (le defaut, deny-by-default) : on TRAVERSE le spread. A chacune des 4 executions
    on paie un demi-spread -> spot_spread + perp_spread au total, plus 4 frais taker.

    EN MAKER : on ENCAISSE le demi-spread... **si on est rempli.** T1 a mesure ce que vaut
    cette hypothese : sur CASHCAT, 0,33 % du flux atteignait le fond de la file. Un maker qui
    n'est pas rempli n'a pas de position -- et un maker rempli sur UNE SEULE jambe n'est pas
    couvert : il est NU. Le mode maker est donc une BORNE OPTIMISTE, jamais un plan.
    """
    s = max(0.0, float(spot_spread_bps))
    p = max(0.0, float(perp_spread_bps))
    if maker:
        # borne optimiste : on encaisse les demi-spreads, on paie 4 frais maker
        return COUT_MAKER_2_JAMBES_BPS - (s + p)
    return COUT_TAKER_2_JAMBES_BPS + s + p

# MODELE CORRIGE (2026-07-12) -- MON PREMIER MODELE ETAIT FAUX, ET TROP PESSIMISTE.
#
# Je supposais que le funding DECROIT VERS ZERO (persistance 0,70/h). La somme geometrique
# plafonnait alors a f/(1-0,70) = 3,33 x f. D'ou un seuil "impossible" de 1,8 bps/h.
#
# LA FORMULE OFFICIELLE D'HYPERLIQUID DIT AUTRE CHOSE :
#     F = premium + clamp(interest - premium, -0,0005, +0,0005)
# ou `interest` est FIXE PAR LE PROTOCOLE : 0,01 % / 8 h = 0,00125 %/h = **0,125 bps/h**.
# La doc l'ecrit noir sur blanc : "11,6 % APR paid to short".
#
# ET C'EST EXACTEMENT LA MEDIANE QU'ON AVAIT MESUREE (0,1250 bps/h).
# Verifie sur 105 096 releves : **57,2 % des observations sont EXACTEMENT a 0,125 bps/h**.
#
# Ce n'etait pas du bruit. C'est le PLANCHER STRUCTUREL du protocole. Il ne decroit pas vers
# zero : le funding decroit vers CE PLANCHER. Le carry ne plafonne donc PAS -- il s'accumule.
PLANCHER_PROTOCOLAIRE_BPS_H = 0.125          # 0,01 % / 8 h, fixe par Hyperliquid

# Le PREMIUM (l'exces au-dessus du plancher) lui, se degrade bien : persistance 0,70/h mesuree.
PERSISTANCE_PREMIUM_1H = 0.70

# Retro-compatibilite : l'ancien nom pointait sur la persistance du premium.
PERSISTANCE_1H = PERSISTANCE_PREMIUM_1H

# Sous ce seuil, la jambe spot ne peut pas etre montee : le carry n'existe pas.
LIQUIDITE_SPOT_MIN_USD = 2_500.0

MOTIF_PAS_DE_SPOT = "AUCUN_MARCHE_SPOT_PAS_DE_COUVERTURE_POSSIBLE"
MOTIF_SPOT_ILLIQUIDE = "SPOT_TROP_MINCE_POUR_MONTER_LA_JAMBE"
MOTIF_BASE_TROP_CHERE = "LA_BASE_COUTE_PLUS_QUE_LE_FUNDING_NE_RAPPORTE"
MOTIF_FUNDING_TROP_FAIBLE = "FUNDING_NE_COUVRE_PAS_LES_FRAIS_DES_DEUX_JAMBES"
MOTIF_INCONNU = "DONNEE_MANQUANTE_NO_TRADE"
MOTIF_BASE_CONVERGENCE = "CARRY_BASE_CONVERGENCE_VIABLE"

#: R3 — la base doit payer l'aller-retour AVEC une marge de securite : >= 130 % des frais des
#: deux jambes. En-dessous, une base "presque suffisante" laisserait la position dependre d'un
#: funding qu'elle n'a pas. Cliquet teste : ne pas adoucir apres avoir vu une opportunite ratee.
SEUIL_BASE_SEULE_FRACTION = 1.3
#: R3 — funding tolere pendant qu'on attend la convergence : strictement au-dessus du seuil
#: d'hemorragie d'A6 (-0,5 bps/h = -12 bps/jour). En-dessous, le loyer mange la capture.
FUNDING_MIN_TOLERE_BPS_H = -0.5


@dataclass(frozen=True, slots=True)
class CarryNeutre:
    coin: str
    funding_bps_h: float
    base_bps: float                 # (perp - spot) / spot. Positif = le perp est PLUS CHER.
    liquidite_spot_usd: float
    cout_entree_bps: float          # frais des 2 jambes + la base subie
    heures_pour_rentabiliser: float | None
    funding_restant_a_ce_moment: float | None
    #: 🔴 UNITE REPAREE LE 19/07. Ce champ publiait le gain cumule sur TOUT l'horizon (30 j)
    #: sous un nom de taux journalier : PURR affichait « +49,7 bps/24h » avec un funding au
    #: plancher qui ne rend que ~3 bps/24h BRUTS. Un x30 de complaisance. La rotation A7, qui
    #: compare des taux JOURNALIERS a un cout one-shot, voyait des surplus fantomes x30 --
    #: c'est un des moteurs des 29 rotations du churn (-5,07 $). Desormais : VRAI net moyen
    #: par 24 h sur l'horizon. Le cumul, lui, vit dans `gain_net_horizon_bps`.
    gain_net_24h_bps: float | None
    viable: bool
    motif: str
    note: str = ""
    #: gain net CUMULE sur l'horizon de detention (l'ancienne valeur, sous son vrai nom).
    gain_net_horizon_bps: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "funding_bps_h": self.funding_bps_h,
            "base_bps": self.base_bps,
            "liquidite_spot_usd": self.liquidite_spot_usd,
            "cout_entree_bps": self.cout_entree_bps,
            "heures_pour_rentabiliser": self.heures_pour_rentabiliser,
            "funding_restant_a_ce_moment": self.funding_restant_a_ce_moment,
            "gain_net_24h_bps": self.gain_net_24h_bps,
            "gain_net_horizon_bps": self.gain_net_horizon_bps,
            "viable": self.viable,
            "motif": self.motif,
            "note": self.note,
            "structure": "LONG spot + SHORT perp, meme taille -> le prix s'annule",
            "real_execution": False,
        }


def funding_cumule_bps(heures: float, funding_initial_bps_h: float,
                       persistance: float = PERSISTANCE_PREMIUM_1H,
                       plancher: float = PLANCHER_PROTOCOLAIRE_BPS_H) -> float:
    """Le funding se decompose en DEUX parties, et c'est TOUT le sujet :

        funding(t) = PLANCHER (permanent, protocolaire)  +  PREMIUM (transitoire, decroit)

    Le plancher (0,125 bps/h) NE DISPARAIT PAS : c'est la composante d'interet du protocole,
    payee par les longs aux shorts, par construction. Le premium, lui, se degrade a 0,70/h.

    Mon premier modele faisait decroitre le TOUT vers zero. C'etait faux -- et ca fabriquait
    un seuil de rentabilite impossible (1,8 bps/h). Le vrai carry S'ACCUMULE.
    """
    h = int(max(0.0, heures))
    f0 = float(funding_initial_bps_h)
    sol = min(float(plancher), f0) if f0 > 0 else 0.0     # le plancher ne depasse jamais le total
    premium = max(0.0, f0 - sol)

    total = sol * h                                        # le plancher : LINEAIRE, sans fin
    p = premium
    for _ in range(h):                                     # le premium : geometrique, s'eteint
        total += p
        p *= persistance
    return total


def evaluer_carry_neutre(
    *,
    coin: str,
    funding_bps_h: float | None,
    base_bps: float | None,
    liquidite_spot_usd: float | None,
    maker: bool = True,
    horizon_h: float = 720.0,          # 30 JOURS -- un carry delta-neutre se tient, il ne se
                                       # scalpe pas. Il n'y a AUCUN risque de prix a fuir.
                                       # Le juger sur 24 h, c'etait mon erreur : les 6 bps
                                       # d'entree sont un investissement, pas une perte.
    # --- T2b / #588 : les TROIS entrees du risque de liquidation. Sans elles -> refus.
    levier_max: float | None = None,           # levier max du perp (HYPE : 10x -> maintenance 5 %)
    marge_ratio: float | None = None,          # m = marge du perp / notionnel
    pire_hausse_observee: float | None = None,  # mesuree sur des prix REELS, sur l'horizon tenu
) -> CarryNeutre:
    """Le carry delta-neutre paie-t-il ? DENY-BY-DEFAULT.

    `base_bps` = (perp - spot) / spot en bps.
      * base POSITIVE  -> le perp est plus cher -> on SHORT haut, on achete le spot bas :
                          la base joue POUR nous a l'entree.
      * base NEGATIVE  -> on paie la base a l'entree.
    On encaisse le funding si `funding_bps_h > 0` (les longs paient les shorts, et on est short
    le perp).
    """
    if funding_bps_h is None or base_bps is None or liquidite_spot_usd is None:
        return CarryNeutre(coin, 0.0, 0.0, 0.0, 0.0, None, None, None, False, MOTIF_INCONNU,
                           "une jambe qu'on ne mesure pas est une jambe qu'on n'a pas")

    if liquidite_spot_usd <= 0:
        return CarryNeutre(coin, funding_bps_h, base_bps, 0.0, 0.0, None, None, None,
                           False, MOTIF_PAS_DE_SPOT,
                           "sans marche spot, la couverture est IMPOSSIBLE -- on retombe sur la "
                           "jambe nue, qui est une zone morte")

    if liquidite_spot_usd < LIQUIDITE_SPOT_MIN_USD:
        return CarryNeutre(coin, funding_bps_h, base_bps, liquidite_spot_usd, 0.0, None, None,
                           None, False, MOTIF_SPOT_ILLIQUIDE,
                           "spot a %.0f $ : on ne peut pas monter la jambe. Un carry qu'on ne "
                           "peut pas construire n'existe pas." % liquidite_spot_usd)

    frais = COUT_MAKER_2_JAMBES_BPS if maker else COUT_TAKER_2_JAMBES_BPS
    # la base joue POUR nous si le perp est plus cher (on le short haut)
    cout_entree = frais - base_bps

    # on n'encaisse le funding que si on est du BON cote : short perp encaisse un funding POSITIF
    funding_encaisse_h = max(0.0, float(funding_bps_h))
    base_paie_seule = (base_bps >= frais * SEUIL_BASE_SEULE_FRACTION
                       and float(funding_bps_h) > FUNDING_MIN_TOLERE_BPS_H)
    if funding_encaisse_h <= 0 and not base_paie_seule:
        if base_bps >= frais * SEUIL_BASE_SEULE_FRACTION:
            # la base payait, mais le funding est en HEMORRAGIE (<= -0,5 bps/h = -12 bps/jour) :
            # le loyer mangerait la capture avant la convergence. La note doit dire LA VRAIE
            # cause -- une note qui accuse le mauvais garde fabrique de faux diagnostics.
            note = ("base %.1f bps suffisante, mais funding %.2f bps/h <= %.1f (hemorragie) : "
                    "le loyer mange la capture" % (base_bps, funding_bps_h,
                                                   FUNDING_MIN_TOLERE_BPS_H))
        else:
            note = ("funding negatif : short le perp PAIE au lieu d'encaisser (et la base "
                    "%.1f bps < %.1f = %.0f%% des frais : elle ne paie pas l'aller-retour a "
                    "elle seule)" % (base_bps, frais * SEUIL_BASE_SEULE_FRACTION,
                                     SEUIL_BASE_SEULE_FRACTION * 100))
        return CarryNeutre(coin, funding_bps_h, base_bps, liquidite_spot_usd, cout_entree,
                           None, None, None, False, MOTIF_FUNDING_TROP_FAIBLE, note)
    # R3 (19/07 soir) — LA PORTE BASE-CONVERGENCE. Le SEUL PnL realise positif du ledger vient
    # des captures de base (+0,12 $ x3, motif BASE_CONVERGEE_PREMIUM_CAPTURE). Avant : un coin
    # dont la base payait l'aller-retour A ELLE SEULE etait quand meme refuse si son funding
    # etait <= 0 -- on jetait la strategie qui GAGNE au nom de celle qui attend. Desormais :
    # base >= 130 % des frais ET funding > -0,5 bps/h (seuil d'hemorragie, coherent avec A6)
    # -> on entre pour la CONVERGENCE, le funding legerement negatif n'est qu'un petit loyer.
    # La sortie A5 (BASE_CONVERGEE_PREMIUM_CAPTURE) realise le gain ; le verrou de liquidation
    # s'applique comme a tout le monde.

    # combien d'heures pour rembourser le cout d'entree ?
    # Le plancher protocolaire est PERMANENT : meme un carry lent finit par rembourser.
    # Ce n'est plus une question de "est-ce possible", mais de "en combien de temps".
    heures = None
    for h in range(1, 24 * 30 + 1):               # jusqu'a 30 jours -- une position delta-neutre
        if funding_cumule_bps(h, funding_encaisse_h) >= cout_entree:
            heures = float(h)
            break

    restant = (funding_encaisse_h * (PERSISTANCE_1H ** heures)) if heures else None
    # `gain_horizon` = net CUMULE sur l'horizon (30 j par defaut). Le publier tel quel dans un
    # champ nomme "24h" etait le bug d'unite du 19/07 (x30 de complaisance). On garde le cumul
    # pour le verdict `viable` (rembourse ET gagne sur l'horizon), et on publie a cote le VRAI
    # net moyen par 24 h -- c'est LUI que la rotation et le dashboard doivent voir.
    jours_horizon = max(1.0, float(horizon_h) / 24.0)
    gain_horizon = funding_cumule_bps(horizon_h, funding_encaisse_h) - cout_entree

    if heures is None:
        return CarryNeutre(coin, funding_bps_h, base_bps, liquidite_spot_usd, cout_entree,
                           None, None, round(gain_horizon / jours_horizon, 3), False,
                           MOTIF_BASE_TROP_CHERE,
                           "le funding s'evapore (persistance %.2f/h) avant d'avoir rembourse "
                           "%.1f bps de cout d'entree" % (PERSISTANCE_1H, cout_entree),
                           gain_net_horizon_bps=round(gain_horizon, 3))

    # VIABLE = il rembourse ET il gagne sur l'horizon de detention. Pas "il gagne en 24 h".
    viable = (heures is not None) and (gain_horizon > 0)

    # 🔴 T2b / #588 -- LE VERROU QUI MANQUAIT, ET QUI MORD MAINTENANT.
    # « Le prix s'annule » est vrai pour le PORTEFEUILLE, FAUX pour le COMPTE PERP : le gain de la
    # jambe spot est en HYPE, pas en USDC -- il ne recharge PAS la marge du short. Mesure sur 200
    # jours de prix HYPE reels : la pire hausse subie sur 30 j de detention est de **+95,6 %**.
    # Un carry evalue sans son risque de liquidation est un carry evalue sur ses BONNES nouvelles.
    if viable:
        liq = evaluer_risque_liquidation(
            coin=coin, levier_max=levier_max, marge_ratio=marge_ratio,
            pire_mouvement_observe=pire_hausse_observee, rendement_brut_bps=gain_horizon,
        )
        if not liq.viable:
            return CarryNeutre(
                coin=coin, funding_bps_h=round(funding_bps_h, 4), base_bps=round(base_bps, 2),
                liquidite_spot_usd=round(liquidite_spot_usd, 0),
                cout_entree_bps=round(cout_entree, 2), heures_pour_rentabiliser=heures,
                funding_restant_a_ce_moment=round(restant, 4) if restant else None,
                # le rendement AFFICHE devient celui du capital REELLEMENT immobilise (N + M)
                gain_net_24h_bps=round(liq.rendement_sur_capital_bps / jours_horizon, 3),
                viable=False, motif=liq.motif, note=liq.note,
                gain_net_horizon_bps=round(liq.rendement_sur_capital_bps, 3),
            )
        # la jambe perp survit : on publie le rendement sur le CAPITAL TOTAL, pas sur le notionnel
        gain_horizon = liq.rendement_sur_capital_bps
    return CarryNeutre(
        coin=coin, funding_bps_h=round(funding_bps_h, 4), base_bps=round(base_bps, 2),
        liquidite_spot_usd=round(liquidite_spot_usd, 0),
        cout_entree_bps=round(cout_entree, 2),
        heures_pour_rentabiliser=heures,
        funding_restant_a_ce_moment=round(restant, 4) if restant else None,
        gain_net_24h_bps=round(gain_horizon / jours_horizon, 3),
        viable=viable,
        # attribution honnete : une entree payee par la BASE (funding <= 0) porte son propre
        # motif -> le PnL par strategie (P1 ops) distingue portage et convergence.
        motif=(("CARRY_NEUTRE_VIABLE" if funding_encaisse_h > 0 else MOTIF_BASE_CONVERGENCE)
               if viable else MOTIF_BASE_TROP_CHERE),
        note=("rembourse en %.0f h (%.1f j), puis portage pur -- %.1f bps nets sur %.0f jours "
              "(soit %.2f bps par 24 h en moyenne)"
              % (heures, heures / 24.0, gain_horizon, horizon_h / 24.0,
                 gain_horizon / jours_horizon)) if viable
             else ("rembourse en %.0f h mais le carry reste negatif sur l'horizon"
                   % (heures or 0)),
        gain_net_horizon_bps=round(gain_horizon, 3),
    )


__all__ = [
    "COUT_MAKER_2_JAMBES_BPS", "COUT_TAKER_2_JAMBES_BPS", "LIQUIDITE_SPOT_MIN_USD",
    "MAKER_BPS", "MOTIF_BASE_TROP_CHERE", "MOTIF_FUNDING_TROP_FAIBLE", "MOTIF_INCONNU",
    "MOTIF_PAS_DE_SPOT", "MOTIF_SPOT_ILLIQUIDE", "PERSISTANCE_1H", "TAKER_BPS",
    "CarryNeutre", "evaluer_carry_neutre", "funding_cumule_bps",
]
