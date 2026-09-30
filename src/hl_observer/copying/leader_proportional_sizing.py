"""ALPHA-8 — taille de copie FIDÈLE au leader, mais BORNÉE par la capacité (paper, pur, 0 réseau, 0 ordre).

Formule pré-enregistrée :

    taille_cible = min( capacite_l2_usd , budget_risque_usd , equity_suiveur * clip(delta_leader / NAV_leader) )

Trois règles de vérité, toutes testées :

1. **NAV du leader absent ⇒ la proportion n'est PAS mesurable.** On ne remplace jamais un NAV manquant par
   une taille fixe « raisonnable » : sans dénominateur, la fidélité au leader n'existe pas.
2. **Aucune taille ne dépend d'un résultat futur.** La signature publique refuse tout paramètre de PnL /
   prix forward : dimensionner avec ce qu'on ne saurait pas encore, c'est du lookahead déguisé en sizing.
3. **La contrainte qui mord est NOMMÉE.** Une taille qui sort sans dire ce qui l'a bornée empêche de
   comprendre pourquoi la stratégie ne scale pas.

Les sorties du leader sont copiées **proportionnellement à NOTRE position**, jamais au notionnel initial —
sinon un REDUCE de 40 % appliqué à la taille d'origine sur-vend une position déjà réduite.

Ce module ne décide d'aucune allocation : `verdict_allocation` exige que le **ROI net ET le drawdown** OOS
s'améliorent, et ne dit jamais oui parce que le PnL nominal a grossi avec l'exposition.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

VERSION = "leader_proportional_sizing_v1"

#: Bornes PRÉ-ENREGISTRÉES de la fraction copiée (part du portefeuille du leader répliquée).
FRACTION_MIN = 0.0
FRACTION_MAX = 0.25

#: Motifs de bornage, du plus au moins contraignant — sert à nommer ce qui a limité la taille.
BORNES = ("CAPACITE_L2", "BUDGET_RISQUE", "PROPORTION_LEADER")


def _positif(valeur: Any) -> float | None:
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def fraction_leader(delta_notional_usd: Any, nav_leader_usd: Any, *,
                    plafond: float = FRACTION_MAX) -> dict[str, Any]:
    """Part du portefeuille du leader engagée sur ce mouvement, bornée. `None` si le NAV manque."""
    nav = _positif(nav_leader_usd)
    if nav is None:
        return {"fraction": None, "fraction_brute": None, "plafonnee": None,
                "raison": "NAV_LEADER_NON_MESURABLE"}
    try:
        delta = abs(float(delta_notional_usd))
    except (TypeError, ValueError):
        return {"fraction": None, "fraction_brute": None, "plafonnee": None,
                "raison": "DELTA_LEADER_NON_MESURABLE"}
    brute = delta / nav
    bornee = max(FRACTION_MIN, min(brute, float(plafond)))
    return {"fraction": round(bornee, 8), "fraction_brute": round(brute, 8),
            "plafonnee": bool(brute > float(plafond)), "raison": None}


def taille_cible(*, capacite_l2_usd: Any, budget_risque_usd: Any, equity_suiveur_usd: Any,
                 delta_notional_leader_usd: Any, nav_leader_usd: Any,
                 plafond_fraction: float = FRACTION_MAX) -> dict[str, Any]:
    """Taille de copie = minimum des trois bornes. Toute borne non mesurable ⇒ AUCUNE position."""
    frac = fraction_leader(delta_notional_leader_usd, nav_leader_usd, plafond=plafond_fraction)
    equity = _positif(equity_suiveur_usd)
    capacite = _positif(capacite_l2_usd)
    budget = _positif(budget_risque_usd)

    manquantes = []
    if capacite is None:
        manquantes.append("CAPACITE_L2")
    if budget is None:
        manquantes.append("BUDGET_RISQUE")
    if equity is None:
        manquantes.append("EQUITY_SUIVEUR")
    if frac["fraction"] is None:
        manquantes.append(frac["raison"])
    if manquantes:
        return {"taille_usd": None, "borne_active": None, "mesurable": False,
                "manquantes": manquantes, "fraction_leader": frac,
                "raison": "SIZING_NON_MESURABLE", "real_execution": False}

    proportionnelle = equity * frac["fraction"]
    candidats = {"CAPACITE_L2": capacite, "BUDGET_RISQUE": budget, "PROPORTION_LEADER": proportionnelle}
    borne = min(BORNES, key=lambda nom: candidats[nom])
    return {"taille_usd": round(candidats[borne], 6), "borne_active": borne, "mesurable": True,
            "manquantes": [], "fraction_leader": frac, "candidats_usd": {k: round(v, 6) for k, v in candidats.items()},
            "real_execution": False}


def appliquer_caps(taille_usd: Any, *, expositions: Mapping[str, float] | None = None,
                   caps: Mapping[str, float] | None = None, coin: str | None = None,
                   direction: str | None = None, cluster: str | None = None) -> dict[str, Any]:
    """Rabote la taille par les plafonds coin / direction / cluster déjà consommés. Nomme le cap qui mord."""
    base = _positif(taille_usd)
    if base is None:
        return {"taille_usd": None, "cap_actif": None, "mesurable": False, "raison": "TAILLE_NON_MESURABLE"}
    exp = dict(expositions or {})
    plafonds = dict(caps or {})
    restants: dict[str, float] = {}
    for nom, cle in (("CAP_COIN", coin), ("CAP_DIRECTION", direction), ("CAP_CLUSTER", cluster)):
        if cle is None or nom not in plafonds:
            continue
        restants[nom] = max(0.0, float(plafonds[nom]) - float(exp.get(cle, 0.0)))
    if not restants:
        return {"taille_usd": round(base, 6), "cap_actif": None, "mesurable": True, "raison": None}
    cap_nom = min(restants, key=lambda n: restants[n])
    finale = min(base, restants[cap_nom])
    return {"taille_usd": round(finale, 6), "cap_actif": cap_nom if finale < base else None,
            "restants_usd": {k: round(v, 6) for k, v in restants.items()}, "mesurable": True, "raison": None}


def copier_reduce(*, fraction_reduite_leader: Any, position_suiveur_usd: Any) -> dict[str, Any]:
    """REDUCE/CLOSE proportionnels à NOTRE position courante, jamais au notionnel initial."""
    position = _positif(position_suiveur_usd)
    try:
        fraction = float(fraction_reduite_leader)
    except (TypeError, ValueError):
        fraction = -1.0
    if position is None or not (0.0 <= fraction <= 1.0):
        return {"reduction_usd": None, "position_restante_usd": None, "mesurable": False,
                "raison": "REDUCE_NON_MESURABLE"}
    reduction = position * fraction
    return {"reduction_usd": round(reduction, 6), "position_restante_usd": round(position - reduction, 6),
            "fermeture_totale": bool(fraction >= 1.0), "mesurable": True, "raison": None}


def cout_turnover(taille_usd: Any, *, frais_ar_bps: float) -> dict[str, Any]:
    """Turnover et frais d'un aller-retour : une taille plus grande n'est jamais gratuite."""
    base = _positif(taille_usd)
    if base is None:
        return {"turnover_usd": None, "frais_usd": None, "mesurable": False}
    turnover = 2.0 * base
    return {"turnover_usd": round(turnover, 6), "frais_usd": round(base * float(frais_ar_bps) / 1e4, 6),
            "mesurable": True}


def verdict_allocation(*, avec: Mapping[str, Any], sans: Mapping[str, Any],
                       min_episodes: int = 30) -> dict[str, Any]:
    """Retient le sizing proportionnel SEULEMENT si le ROI net s'améliore ET que le drawdown ne s'aggrave pas.

    Un PnL nominal plus gros obtenu en déployant plus de capital n'est pas une amélioration : c'est du levier.
    """
    n_avec = int(avec.get("n_episodes") or 0)
    n_sans = int(sans.get("n_episodes") or 0)
    if min(n_avec, n_sans) < int(min_episodes):
        return {"statut": "NON_CONCLUANT", "retenu": False,
                "raison": "%d/%d episodes < %d requis" % (n_avec, n_sans, min_episodes)}
    roi_avec, roi_sans = avec.get("roi_net"), sans.get("roi_net")
    dd_avec, dd_sans = avec.get("max_drawdown"), sans.get("max_drawdown")
    if not all(isinstance(v, (int, float)) for v in (roi_avec, roi_sans, dd_avec, dd_sans)):
        return {"statut": "NON_MESURABLE", "retenu": False, "raison": "ROI ou drawdown absent"}
    roi_mieux = float(roi_avec) > float(roi_sans)
    # drawdown exprimé en valeur négative ou positive : on compare la magnitude
    dd_pas_pire = abs(float(dd_avec)) <= abs(float(dd_sans))
    retenu = bool(roi_mieux and dd_pas_pire)
    return {"statut": "RETENU" if retenu else "REJETE", "retenu": retenu,
            "roi_ameliore": roi_mieux, "drawdown_pas_degrade": dd_pas_pire,
            "delta_roi": round(float(roi_avec) - float(roi_sans), 6),
            "delta_drawdown": round(abs(float(dd_avec)) - abs(float(dd_sans)), 6),
            "raison": None if retenu else "exige ROI net en hausse ET drawdown non degrade"}


__all__ = [
    "VERSION", "FRACTION_MIN", "FRACTION_MAX", "BORNES", "fraction_leader", "taille_cible",
    "appliquer_caps", "copier_reduce", "cout_turnover", "verdict_allocation",
]
