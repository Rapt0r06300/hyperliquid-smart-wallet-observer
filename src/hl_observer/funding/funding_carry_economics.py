"""LE CARRY DE FUNDING N'EST PAS UN ARBITRAGE S'IL N'EST PAS COUVERT (2026-07-11).

MESURE REELLE, 232 marches Hyperliquid, 9 512 releves, fenetre 1,34 h
(`runtime/replay/funding*.jsonl` -- outil : `tools/mesurer_courbe_sniper.py` et l'autopsie carry) :

    |funding| median ................... 0,125 bps/h
    marches payant >= 1 bps/h .......... 1 / 232   (0,4 %)
    persistance du funding a 1 h ....... +0,70   <-- REEL, ce n'est PAS du bruit
    |mouvement de prix| median sur 1 h . ~35 bps

    RATIO median funding / bruit de prix : 0,0036

    => Pour 1 bps de funding encaisse, une jambe NUE subit ~281 bps de mouvement de prix.

CE QUE CA VEUT DIRE, ET C'EST CONTRE-INTUITIF :

Le funding est le PREMIER signal de ce projet qui a une structure reelle. Sa persistance (+0,70 a
1 h) ecrase le copy-trading (rapport signal/bruit 0,03). Il est PREVISIBLE.

Mais prevoir un revenu de 0,125 bps/h en encaissant 35 bps de bruit de prix, ce n'est pas un
arbitrage : c'est un pari directionnel avec un coupon. Le coupon ne change rien a l'issue.

PIRE -- ET C'EST LE PIEGE QUI A FAILLI NOUS AVOIR :

Le gate historique (>= 2,5 bps/h) ne laissait passer QU'UN marche : CASHCAT. Or CASHCAT bouge de
**219 bps par heure**. Le funding y est eleve PRECISEMENT PARCE QUE le risque y est extreme.
**Le gate selectionnait le marche le plus dangereux de la plateforme.** Un seuil de funding plus
haut ne filtre pas le risque : il le CONCENTRE.

LA REGLE POSEE ICI (deny-by-default) :

    1. Une jambe NON COUVERTE est REFUSEE. Toujours. Peu importe le funding.
       (le code actuel a UNE seule jambe + un `hedge_venue_extra_bps` forfaitaire qui fait
        SEMBLANT d'en avoir une -- le fichier `funding_arb_paper.py` l'avoue ligne 83)
    2. Meme couverte, la position doit couvrir ses couts AVANT que le funding ne se soit
       evapore -- car il se degrade (persistance 0,70/h, pas 1,0).
    3. Un funding inconnu / trop vieux -> NO_TRADE. Jamais une valeur par defaut.

PUR, sans I/O, sans reseau. Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- constantes MESUREES (pas inventees). Source : autopsie 2026-07-11, 232 marches.
PERSISTANCE_1H_MESUREE = 0.70          # autocorrelation du funding a 1 h
RATIO_MEDIAN_FUNDING_SUR_BRUIT = 0.0036
FUNDING_MEDIAN_BPS_H = 0.125

# Une jambe nue doit gagner PLUS que le bruit de prix qu'elle subit. Le ratio median mesure est
# 0,0036 : autant dire jamais. On exige 1.0 -- c'est-a-dire l'impossible, et c'est VOULU :
# la seule facon honnete de faire du carry, c'est de couvrir.
RATIO_MIN_JAMBE_NUE = 1.0

REFUS_NON_COUVERT = "FUNDING_LEG_UNHEDGED_PRICE_RISK_DOMINATES"
REFUS_NOYE = "FUNDING_DROWNED_BY_PRICE_NOISE"
REFUS_FUNDING_INCONNU = "FUNDING_RATE_UNKNOWN_NO_TRADE"
REFUS_TROP_LENT = "FUNDING_DECAYS_BEFORE_COSTS_ARE_COVERED"


@dataclass(frozen=True, slots=True)
class VerdictCarry:
    viable: bool
    motif: str
    funding_bps_h: float
    bruit_prix_bps_h: float
    ratio: float
    heures_pour_couvrir_couts: float | None
    funding_restant_a_ce_moment_bps_h: float | None
    couvert: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "viable": self.viable,
            "motif": self.motif,
            "funding_bps_h": self.funding_bps_h,
            "bruit_prix_bps_h": self.bruit_prix_bps_h,
            "ratio_funding_sur_bruit": self.ratio,
            "heures_pour_couvrir_couts": self.heures_pour_couvrir_couts,
            "funding_restant_a_ce_moment_bps_h": self.funding_restant_a_ce_moment_bps_h,
            "couvert": self.couvert,
            "note": self.note,
            "real_execution": False,
        }


def funding_restant_apres(heures: float, *, funding_initial_bps_h: float,
                          persistance_1h: float = PERSISTANCE_1H_MESUREE) -> float:
    """Le funding se DEGRADE. Persistance mesuree 0,70 par heure -> decroissance geometrique.

    Supposer qu'un funding de 0,8 bps/h le restera pendant 33 heures, c'est se mentir :
    au bout de 33 h il n'en reste rien (0,70 ** 33 ~ 0,000006).
    """
    h = max(0.0, float(heures))
    p = min(max(float(persistance_1h), 0.0), 1.0)
    return float(funding_initial_bps_h) * (p ** h)


def evaluer_carry(
    *,
    funding_bps_h: float | None,
    bruit_prix_bps_h: float | None,
    cout_aller_retour_bps: float,
    couvert: bool,
    heures_detention_max: float = 24.0,
) -> VerdictCarry:
    """Un carry de funding est-il viable ? DENY-BY-DEFAULT.

    `couvert` : y a-t-il une VRAIE jambe opposee qui annule le risque de prix ?
                Un frais forfaitaire n'est pas une couverture.
    """
    # 1. donnee manquante -> on refuse. Jamais de valeur par defaut sur un chiffre qui autorise
    #    une position.
    if funding_bps_h is None or bruit_prix_bps_h is None:
        return VerdictCarry(
            viable=False, motif=REFUS_FUNDING_INCONNU,
            funding_bps_h=0.0, bruit_prix_bps_h=0.0, ratio=0.0,
            heures_pour_couvrir_couts=None, funding_restant_a_ce_moment_bps_h=None,
            couvert=bool(couvert),
            note="funding ou volatilite inconnu : une position ne s'ouvre pas sur une inconnue",
        )

    f = abs(float(funding_bps_h))
    bruit = abs(float(bruit_prix_bps_h))
    ratio = (f / bruit) if bruit > 0 else float("inf")

    heures = (float(cout_aller_retour_bps) / f) if f > 0 else None
    restant = (funding_restant_apres(heures, funding_initial_bps_h=f)
               if heures is not None else None)

    # 2. NON COUVERT -> refus sec. C'est la regle dure, celle que la mesure impose.
    if not couvert:
        return VerdictCarry(
            viable=False, motif=REFUS_NON_COUVERT,
            funding_bps_h=f, bruit_prix_bps_h=bruit, ratio=round(ratio, 6),
            heures_pour_couvrir_couts=heures, funding_restant_a_ce_moment_bps_h=restant,
            couvert=False,
            note=(
                f"jambe nue : {f:.3f} bps/h de funding contre {bruit:.1f} bps/h de mouvement de "
                f"prix. Ce n'est pas un arbitrage, c'est un pari directionnel avec un coupon."
            ),
        )

    # 3. Meme couvert : le funding doit encore exister quand les couts sont amortis.
    if heures is None or heures > heures_detention_max:
        return VerdictCarry(
            viable=False, motif=REFUS_TROP_LENT,
            funding_bps_h=f, bruit_prix_bps_h=bruit, ratio=round(ratio, 6),
            heures_pour_couvrir_couts=heures, funding_restant_a_ce_moment_bps_h=restant,
            couvert=True,
            note=(
                f"il faut {heures:.1f} h pour couvrir {cout_aller_retour_bps:.1f} bps de couts, "
                f"mais a ce moment-la il ne reste que {(restant or 0.0):.4f} bps/h de funding "
                f"(persistance mesuree {PERSISTANCE_1H_MESUREE})."
                if heures is not None else "funding nul : rien a encaisser"
            ),
        )

    return VerdictCarry(
        viable=True, motif="FUNDING_CARRY_HEDGED_AND_ECONOMIC",
        funding_bps_h=f, bruit_prix_bps_h=bruit, ratio=round(ratio, 6),
        heures_pour_couvrir_couts=heures, funding_restant_a_ce_moment_bps_h=restant,
        couvert=True,
        note=(
            f"couvert, couts amortis en {heures:.1f} h, funding encore a "
            f"{(restant or 0.0):.3f} bps/h a ce moment."
        ),
    )


def piege_du_seuil_de_funding(marches: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """LE PIEGE, RENDU VISIBLE : monter le seuil de funding CONCENTRE le risque.

    `marches` : {coin: (funding_bps_h, bruit_prix_bps_h)}

    Mesure du 2026-07-11 : le seuil a 2,5 bps/h ne laissait passer que CASHCAT... qui bouge de
    219 bps/h. Le seuil ne filtrait pas le risque, il selectionnait le marche le plus violent.
    """
    lignes = []
    for seuil in (0.0, 0.5, 1.0, 2.5, 5.0):
        retenus = {c: v for c, v in marches.items() if abs(v[0]) >= seuil}
        if not retenus:
            lignes.append({"seuil_bps_h": seuil, "n_marches": 0, "bruit_moyen_bps_h": None})
            continue
        bruit_moy = sum(abs(v[1]) for v in retenus.values()) / len(retenus)
        lignes.append({
            "seuil_bps_h": seuil,
            "n_marches": len(retenus),
            "bruit_moyen_bps_h": round(bruit_moy, 2),
            "coins": sorted(retenus)[:5],
        })
    return {
        "lignes": lignes,
        "avertissement": (
            "Si le bruit moyen MONTE quand le seuil monte, le gate ne filtre pas le risque : "
            "il le concentre. Un funding eleve est eleve PARCE QUE le marche est dangereux."
        ),
        "real_execution": False,
    }


__all__ = [
    "FUNDING_MEDIAN_BPS_H", "PERSISTANCE_1H_MESUREE", "RATIO_MEDIAN_FUNDING_SUR_BRUIT",
    "RATIO_MIN_JAMBE_NUE",
    "REFUS_FUNDING_INCONNU", "REFUS_NON_COUVERT", "REFUS_NOYE", "REFUS_TROP_LENT",
    "VerdictCarry", "evaluer_carry", "funding_restant_apres", "piege_du_seuil_de_funding",
]
