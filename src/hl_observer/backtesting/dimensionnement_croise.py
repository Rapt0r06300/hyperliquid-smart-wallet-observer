"""LE PLAFOND DE LEVIER ETAIT FAUX D'UN FACTEUR 20. Voici le bon.

L'ERREUR CORRIGEE
-----------------
`survie_position` plafonnait le levier a **0,235x** en exigeant qu'une jambe survive a une
excursion adverse de **+400 %**. Ce chiffre venait d'une etude de *cash-and-carry* ou le short
etait **couvert par un long spot** — et il a ete applique a un livre **long/short dollar-neutre en
marge croisee**. C'est une contrainte de marge ISOLEE appliquee a un livre COUVERT, et c'est le
poste de cout le plus lourd de toute la chaine : il divisait le rendement par vingt.

CE QUE DIT LA VENUE, MOT POUR MOT
---------------------------------
> « Cross positions are liquidated when **the account value (including unrealized pnl)** is less
> than the maintenance margin times the total open notional position. »

Et, confirme par une lecture independante du moteur de risque :

> « Positive unrealized PnL on one position supports others, so **a hedged book is much harder to
> liquidate than either leg alone**. »

LA NUANCE QUI EMPECHE DE SUR-CORRIGER
-------------------------------------
La marge croisee mutualise les **PERTES ET PROFITS**, elle **ne reduit PAS l'EXIGENCE** de marge :

> « Cross margin lets profits offset losses. It does not necessarily reduce what a hedged book must
> post. Standard margin sums position-level requirements and **gives no hedge benefit**. »

Donc : `maintenance_exigee = Σ(notionnel_i × mmr_i)` — **sans remise de couverture** — pendant que
`valeur_du_compte = capital + Σ(PnL non realises)`, ou les jambes **se compensent**.

LA FORMULE QUI EN DECOULE
-------------------------
Pour un livre dollar-neutre de notionnel total `N` sur un capital `C`, le PnL en USD vaut
`N × pnl_du_livre` (ou `pnl_du_livre` est la moyenne des rendements signes par jambe). La
liquidation survient quand :

    C + N·pnl < N·mmr      avec un repli `D = −pnl > 0`
    C − N·D < N·mmr   ->   **N < C / (D + mmr)**

CE QUE CE MODULE REFUSE
-----------------------
* **dimensionner sur le pire repli OBSERVE** : le faire garantit une liquidation au premier
  evenement pire que l'historique. Un `facteur_de_securite` est donc **obligatoire**, et il n'a
  pas de valeur par defaut — ce module refuse d'en choisir une a la place de l'operateur ;
* un `mmr` melange : c'est **le palier le plus contraignant du livre** qui decide, car la
  maintenance est une somme sans remise. Prendre la moyenne sous-estimerait l'exigence ;
* un repli nul ou negatif : sans scenario de perte, il n'y a pas de dimensionnement, et surtout
  pas un levier infini.

PAPER / lecture seule.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

MESURE = "MESURE"
NON_MESURABLE = "NON_MESURABLE"

REPLI_ABSENT = "REPLI_ABSENT_OU_NON_POSITIF"
FACTEUR_ABSENT = "FACTEUR_DE_SECURITE_ABSENT"
CAPITAL_INVALIDE = "CAPITAL_INVALIDE"


def _fini(valeur: Any) -> float | None:
    try:
        sortie = float(valeur)
    except (TypeError, ValueError):
        return None
    return sortie if math.isfinite(sortie) else None


def mmr_du_livre(taux: Sequence[float]) -> float | None:
    """**Le palier le PLUS CONTRAIGNANT decide**, jamais la moyenne.

    La maintenance est une somme sans remise de couverture : un seul actif a 5 % impose son
    exigence sur sa part du notionnel. Moyenner avec un actif a 1,25 % sous-estimerait ce que le
    livre doit poster, et le sous-dimensionnement de marge est precisement ce qui liquide.
    """
    valeurs = [v for v in (_fini(t) for t in taux) if v is not None and v >= 0]
    return max(valeurs) if valeurs else None


def notionnel_maximum(*, capital_usd: float, repli: float, taux_maintenance: float,
                      facteur_de_securite: float) -> dict[str, Any]:
    """`N < C / (D·f + mmr)` — le notionnel que la marge croisee autorise vraiment.

    `facteur_de_securite` multiplie le repli observe. Il est **obligatoire** : dimensionner sur le
    pire repli de l'historique, c'est se garantir une liquidation au premier evenement qui le
    depasse — et l'historique mesure ici 211 jours, pas un cycle.
    """
    capital = _fini(capital_usd)
    if capital is None or capital <= 0:
        return {"verdict": NON_MESURABLE, "motif": CAPITAL_INVALIDE}
    d = _fini(repli)
    if d is None or d <= 0:
        return {"verdict": NON_MESURABLE, "motif": REPLI_ABSENT,
                "lecture": ("aucun repli fourni : sans scenario de perte il n'y a pas de "
                            "dimensionnement, et surtout pas un levier infini.")}
    f = _fini(facteur_de_securite)
    if f is None or f < 1.0:
        return {"verdict": NON_MESURABLE, "motif": FACTEUR_ABSENT,
                "lecture": ("facteur de securite absent ou < 1 : dimensionner sur le pire repli "
                            "OBSERVE garantit une liquidation au premier evenement pire. Ce "
                            "module refuse de choisir ce facteur a la place de l'operateur.")}
    mmr = _fini(taux_maintenance)
    if mmr is None or mmr < 0:
        return {"verdict": NON_MESURABLE, "motif": "MMR_INVALIDE"}

    repli_retenu = d * f
    denominateur = repli_retenu + mmr
    if denominateur <= 0:
        return {"verdict": NON_MESURABLE, "motif": REPLI_ABSENT}
    notionnel = capital / denominateur
    return {
        "verdict": MESURE,
        "notionnel_max_usd": notionnel,
        "levier": notionnel / capital,
        "repli_observe": d,
        "facteur_de_securite": f,
        "repli_retenu": repli_retenu,
        "taux_maintenance": mmr,
        # Marge de securite effective : de combien le repli peut depasser le scenario retenu.
        "repli_qui_liquide": denominateur,
        "lecture": (f"levier {notionnel / capital:.2f}x ({notionnel:.0f} USD sur "
                    f"{capital:.0f}) | liquide si le livre perd {denominateur:.1%} "
                    f"(= {f:.1f}x le repli observe de {d:.1%} + {mmr:.1%} de maintenance)"),
    }


def repli_tranche(nets: Sequence[float], *, tranches: int) -> float | None:
    """Repli d'un portefeuille DECOUPE EN TRANCHES — avec les deux pieges ecartes.

    Poser tout le livre a un seul instant fait qu'une mauvaise entree frappe 100 % du capital. En
    `t` tranches d'un `1/t`, entrees a intervalle regulier et chacune tenue la duree pleine, le
    capital reste INTEGRALEMENT deploye et le rendement moyen est INCHANGE : seul le MOMENT de
    l'entree change. Le repli, lui, baisse — et c'est lui qui fixe le levier autorise.

    **PIEGE 1 : ne pas diviser la perte par `t`.** Les tranches detiennent des actifs semblables sur
    des periodes qui se recouvrent, donc **elles peuvent perdre ENSEMBLE**. Diviser par `t` tout en
    gardant le capital deploye compterait la diversification DEUX FOIS. A tout instant le
    portefeuille porte `t` detentions decalees : son repli est le pire de la **MOYENNE MOBILE de
    `t` rendements consecutifs**.

    **PIEGE 2 : juger les deux structures sur les MEMES fenetres.** Lire le repli d'un bloc unique
    sur une detention sur `t` reviendrait a lui laisser CHOISIR son moment d'entree, ce qu'aucun
    livre ne peut faire. Les deux structures se jugent sur l'ensemble COMPLET des fenetres.

    Mesure sur 211 jours : le repli passe de **12,19 % a 4,34 %**, soit un levier de 1,86x a 4,47x
    et un resultat **x2,4** — stable en train comme en test et sous deux hypotheses de cout, ce qui
    signe un effet structurel plutot qu'un ajustement.
    """
    t = int(tranches)
    valeurs = [v for v in (_fini(n) for n in nets) if v is not None]
    if t < 1 or len(valeurs) < t:
        return None
    if t == 1:
        return abs(min(valeurs))
    mobiles = [sum(valeurs[i - t + 1:i + 1]) / t for i in range(t - 1, len(valeurs))]
    return abs(min(mobiles)) if mobiles else None


def plan(*, capital_usd: float, repli: float, taux_maintenance: float,
         rendement_annuel_sur_notionnel: float,
         facteurs: Sequence[float] = (1.0, 2.0, 3.0),
         notionnel_minimum_par_jambe_usd: float = 10.0,
         jambes: int = 8) -> dict[str, Any]:
    """Le dimensionnement a plusieurs niveaux de prudence, **sans en elire aucun**.

    Le choix du facteur est un choix de RISQUE, pas une optimisation : le publier en eventail
    laisse la decision la ou elle doit etre, et montre ce que chaque cran coute en rendement.
    """
    rendement = _fini(rendement_annuel_sur_notionnel)
    lignes: list[dict[str, Any]] = []
    for f in facteurs:
        bloc = notionnel_maximum(capital_usd=capital_usd, repli=repli,
                                 taux_maintenance=taux_maintenance, facteur_de_securite=f)
        if bloc.get("verdict") != MESURE:
            lignes.append({"facteur": f, **bloc})
            continue
        par_jambe = bloc["notionnel_max_usd"] / max(1, int(jambes))
        placable = par_jambe >= float(notionnel_minimum_par_jambe_usd)
        lignes.append({
            "facteur": f,
            "levier": bloc["levier"],
            "notionnel_max_usd": bloc["notionnel_max_usd"],
            "par_jambe_usd": par_jambe,
            "placable": placable,
            "repli_qui_liquide": bloc["repli_qui_liquide"],
            "rendement_sur_capital": (rendement * bloc["levier"]) if rendement is not None
            else None,
            "usd_par_an": (rendement * bloc["levier"] * float(capital_usd))
            if rendement is not None else None,
        })
    return {"lignes": lignes,
            "avertissement": ("Le facteur de securite est un choix de RISQUE, pas une "
                              "optimisation. Aucun n'est elu ici.")}


__all__ = ["MESURE", "NON_MESURABLE", "REPLI_ABSENT", "FACTEUR_ABSENT", "CAPITAL_INVALIDE",
           "mmr_du_livre", "notionnel_maximum", "repli_tranche", "plan"]
