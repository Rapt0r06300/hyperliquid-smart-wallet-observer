"""AVANT « est-ce rentable ? » : **est-ce PLAÇABLE, et est-ce SURVIVABLE ?**

C'est la couche qui manquait. Tout l'appareil de mesure de ce labo répond à « cet edge survit-il
aux coûts ? » — et aucune ligne ne répondait à « cet ordre serait-il accepté par la venue, et la
position tiendrait-elle jusqu'au bout ? ». Une analyse d'edge sur une position qui se liquide
avant l'échéance ne vaut rien : la recherche le dit en une phrase, **« delta-neutre n'est pas à
l'abri d'une liquidation »**.

LES CONTRAINTES DURES D'HYPERLIQUID (documentation de la venue)
---------------------------------------------------------------
* **notionnel minimum 10 USD** par ordre. Une règle de dimensionnement qui sort 4 USD ne produit
  pas une petite position : elle produit un **ordre REJETÉ**. Sur 350 USD de capital, c'est une
  contrainte vivante, pas théorique.
* **marge de maintenance = la moitié de la marge initiale au levier maximum**, soit de **1,25 %**
  (actifs à 40x, BTC) à **16,7 %** (actifs à 3x). Elle dépend du PALIER, pas de l'actif :
  `maintenance = notionnel * taux − déduction`.
* **prix de liquidation** (formule exacte publiée) :
  `liq = p − side * marge_disponible / taille / (1 − l * side)` avec `l = 1/levier_maintenance`,
  `side = +1` long, `−1` short.
* **la liquidation de secours coûte EN PLUS** : sous 2/3 de la marge de maintenance, la
  liquidation passe par le coffre liquidateur et **la marge de maintenance n'est pas rendue**.
  C'est un terme de perte que personne ne modélise.

LE CALCUL QUI CHANGE LE DIMENSIONNEMENT
---------------------------------------
La recherche mesure, sur des détentions de 31 à 98 jours, des **excursions adverses de +116 %
(BTC) à +400 % (SOL)** sur la jambe short d'un carry. En inversant la formule de la venue, le
levier maximum qui SURVIT à une excursion `e` sur un short vaut :

    e = (1 − mmr·L) / (L · (1 + mmr))   →   L_max = 1 / (e·(1+mmr) + mmr)

Pour SOL (levier max 20x, donc mmr = 2,5 %) et e = 4,00 : **L_max ≈ 0,24x**. Autrement dit, un
short de carry sur SOL doit porter un notionnel **inférieur à 24 % du capital** pour traverser ce
qui a été réellement observé. Sur 350 USD, cela plafonne la jambe short autour de **82 USD de
notionnel** — et le carry est encaissé sur ces 82 USD, pas sur 350.

**Un levier supérieur à 1x sur une jambe de carry n'est pas « agressif » : il est mathématiquement
incompatible avec les excursions déjà mesurées.**

CE QUE CE MODULE REFUSE
-----------------------
* un notionnel sous le minimum de la venue → `REJETE`, jamais « petite position » ;
* un levier nul ou négatif, un prix nul → `NON_MESURABLE` ;
* un `mmr` inconnu → refus, car supposer le plus favorable (1,25 %, réservé à BTC) autoriserait
  silencieusement un levier mortel sur un altcoin ;
* une excursion non fournie → refus de conclure « survivable ». L'absence de scénario adverse
  n'est pas un scénario adverse favorable.

PAPER / lecture seule.
"""
from __future__ import annotations

import math
from typing import Any

LONG, SHORT = 1, -1

PLACABLE = "PLACABLE"
REJETE = "REJETE"
SURVIVABLE = "SURVIVABLE"
NON_SURVIVABLE = "NON_SURVIVABLE"
NON_MESURABLE = "NON_MESURABLE"

SOUS_LE_MINIMUM = "NOTIONNEL_SOUS_LE_MINIMUM"
MMR_INCONNU = "MARGE_DE_MAINTENANCE_INCONNUE"
EXCURSION_ABSENTE = "SCENARIO_ADVERSE_ABSENT"
PARAMETRES_INVALIDES = "PARAMETRES_INVALIDES"

#: Notionnel minimum par ordre sur Hyperliquid, en USD.
NOTIONNEL_MINIMUM_USD = 10.0

#: `maintenance_margin_rate = (1 / levier_max) / 2` — la venue le définit par PALIER.
def taux_de_maintenance(levier_max: float) -> float | None:
    """1,25 % a 40x (BTC), 2,5 % a 20x (SOL), 5 % a 10x (la plupart des alts), 16,7 % a 3x."""
    valeur = _fini(levier_max)
    if valeur is None or valeur <= 0:
        return None
    return (1.0 / valeur) / 2.0


def _fini(valeur: Any) -> float | None:
    try:
        sortie = float(valeur)
    except (TypeError, ValueError):
        return None
    return sortie if math.isfinite(sortie) else None


def ordre_placable(*, notionnel_usd: float) -> dict[str, Any]:
    """Le notionnel minimum de 10 USD n'est pas un detail a 350 USD de capital.

    Une regle de dimensionnement qui sort 4 USD ne produit pas une petite position : elle produit
    un ordre REJETE par la venue, donc une strategie qui ne tourne pas du tout.
    """
    notionnel = _fini(notionnel_usd)
    if notionnel is None or notionnel < 0:
        return {"verdict": NON_MESURABLE, "motif": PARAMETRES_INVALIDES}
    if notionnel < NOTIONNEL_MINIMUM_USD:
        return {"verdict": REJETE, "motif": SOUS_LE_MINIMUM,
                "notionnel_usd": notionnel, "minimum_usd": NOTIONNEL_MINIMUM_USD,
                "lecture": (f"{notionnel:.2f} USD < {NOTIONNEL_MINIMUM_USD:.0f} USD : la venue "
                            "REJETTE cet ordre. Ce n'est pas une petite position, c'est aucune "
                            "position.")}
    return {"verdict": PLACABLE, "notionnel_usd": notionnel,
            "minimum_usd": NOTIONNEL_MINIMUM_USD}


def prix_de_liquidation(*, prix: float, sens: int, taille: float,
                        marge_disponible: float, levier_maintenance: float) -> float | None:
    """La formule exacte publiee par la venue.

        liq = p − side * marge_disponible / taille / (1 − l * side),  l = 1/levier_maintenance

    Un long non liquidable rend une valeur <= 0 : c'est le cas a 1x, et c'est correct.
    """
    p = _fini(prix)
    taille_f = _fini(taille)
    marge = _fini(marge_disponible)
    levier = _fini(levier_maintenance)
    if None in (p, taille_f, marge, levier) or p <= 0 or taille_f <= 0 or levier <= 0:
        return None
    if sens not in (LONG, SHORT):
        return None
    el = 1.0 / levier
    denominateur = 1.0 - el * sens
    if abs(denominateur) < 1e-12:
        return None
    return p - sens * marge / taille_f / denominateur


def excursion_supportee(*, levier: float, taux_maintenance: float,
                        sens: int = SHORT) -> float | None:
    """Mouvement adverse RELATIF que la position traverse avant liquidation.

    Pour un short : `e = (1 − mmr·L) / (L·(1 + mmr))`. Un resultat <= 0 signifie que la position
    est deja sous la marge de maintenance a l'ouverture.
    """
    levier_f = _fini(levier)
    mmr = _fini(taux_maintenance)
    if levier_f is None or mmr is None or levier_f <= 0 or mmr < 0:
        return None
    if sens == SHORT:
        return (1.0 - mmr * levier_f) / (levier_f * (1.0 + mmr))
    if sens == LONG:
        denominateur = levier_f * (1.0 - mmr)
        if abs(denominateur) < 1e-12:
            return None
        return (1.0 - mmr * levier_f) / denominateur
    return None


def levier_maximum_survivable(*, excursion: float, taux_maintenance: float,
                              sens: int = SHORT) -> float | None:
    """Inversion de la formule : quel levier traverse une excursion DEJA MESUREE ?

    `L_max = 1 / (e·(1 + mmr) + mmr)` pour un short. Avec e = 4,00 (les +400 % observes sur SOL)
    et mmr = 2,5 %, cela donne **0,24x** — un notionnel sous le QUART du capital.
    """
    e = _fini(excursion)
    mmr = _fini(taux_maintenance)
    if e is None or mmr is None or e <= 0 or mmr < 0:
        return None
    if sens == SHORT:
        denominateur = e * (1.0 + mmr) + mmr
    elif sens == LONG:
        denominateur = e * (1.0 - mmr) + mmr
    else:
        return None
    if denominateur <= 0:
        return None
    return 1.0 / denominateur


def cout_de_la_liquidation(*, notionnel_usd: float, taux_maintenance: float) -> float | None:
    """Terme de perte que personne ne modelise : sous 2/3 de la marge de maintenance, la
    liquidation passe par le coffre liquidateur et **la marge de maintenance n'est PAS rendue**.
    """
    notionnel = _fini(notionnel_usd)
    mmr = _fini(taux_maintenance)
    if notionnel is None or mmr is None or notionnel < 0 or mmr < 0:
        return None
    return notionnel * mmr


def decider(*, capital_usd: float, notionnel_usd: float, levier_max_venue: float | None,
            excursion_adverse: float | None, sens: int = SHORT) -> dict[str, Any]:
    """Plaçable ? Survivable ? Les deux questions AVANT toute question de rentabilité."""
    placement = ordre_placable(notionnel_usd=notionnel_usd)
    if placement["verdict"] != PLACABLE:
        return {"verdict": placement["verdict"], "motif": placement.get("motif"),
                "placement": placement, "lecture": placement.get("lecture", "")}

    if levier_max_venue is None:
        return {"verdict": NON_MESURABLE, "motif": MMR_INCONNU, "placement": placement,
                "lecture": ("levier maximum de la venue inconnu : supposer le plus favorable "
                            "(1,25 %, reserve a BTC) autoriserait silencieusement un levier "
                            "mortel sur un altcoin. On refuse.")}
    mmr = taux_de_maintenance(levier_max_venue)
    if mmr is None:
        return {"verdict": NON_MESURABLE, "motif": MMR_INCONNU, "placement": placement,
                "lecture": "levier maximum hors domaine."}

    capital = _fini(capital_usd)
    notionnel = float(placement["notionnel_usd"])
    if capital is None or capital <= 0:
        return {"verdict": NON_MESURABLE, "motif": PARAMETRES_INVALIDES, "placement": placement,
                "lecture": "capital invalide."}
    levier = notionnel / capital

    if excursion_adverse is None:
        return {"verdict": NON_MESURABLE, "motif": EXCURSION_ABSENTE, "placement": placement,
                "levier": levier, "taux_maintenance": mmr,
                "excursion_supportee": excursion_supportee(levier=levier, taux_maintenance=mmr,
                                                           sens=sens),
                "lecture": ("aucun scenario adverse fourni : l'ABSENCE de scenario n'est pas un "
                            "scenario favorable. On refuse de conclure « survivable ».")}

    supportee = excursion_supportee(levier=levier, taux_maintenance=mmr, sens=sens)
    plafond = levier_maximum_survivable(excursion=excursion_adverse, taux_maintenance=mmr,
                                        sens=sens)
    if supportee is None or plafond is None:
        return {"verdict": NON_MESURABLE, "motif": PARAMETRES_INVALIDES, "placement": placement,
                "lecture": "parametres hors domaine."}
    survit = supportee >= float(excursion_adverse)
    return {
        "verdict": SURVIVABLE if survit else NON_SURVIVABLE,
        "motif": None if survit else "EXCURSION_ADVERSE_DEPASSE_LA_LIQUIDATION",
        "placement": placement,
        "levier": levier,
        "taux_maintenance": mmr,
        "excursion_supportee": supportee,
        "excursion_adverse": float(excursion_adverse),
        "levier_maximum_survivable": plafond,
        "notionnel_maximum_usd": plafond * capital,
        "cout_si_liquidation_usd": cout_de_la_liquidation(notionnel_usd=notionnel,
                                                          taux_maintenance=mmr),
        "lecture": (
            f"levier {levier:.2f}x | supporte {supportee:+.0%} | "
            f"excursion mesuree {float(excursion_adverse):+.0%} -> "
            + (f"SURVIVABLE (plafond {plafond:.2f}x)" if survit else
               f"NON SURVIVABLE : liquidee avant l'echeance. Plafond {plafond:.2f}x, "
               f"soit {plafond * capital:.0f} USD de notionnel sur {capital:.0f} USD")),
    }


__all__ = ["LONG", "SHORT", "PLACABLE", "REJETE", "SURVIVABLE", "NON_SURVIVABLE",
           "NON_MESURABLE", "SOUS_LE_MINIMUM", "MMR_INCONNU", "EXCURSION_ABSENTE",
           "NOTIONNEL_MINIMUM_USD", "taux_de_maintenance", "ordre_placable",
           "prix_de_liquidation", "excursion_supportee", "levier_maximum_survivable",
           "cout_de_la_liquidation", "decider"]
