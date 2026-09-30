"""COÛTS COMPLETS, DENY-BY-DEFAULT ET ANTI-DOUBLE-COMPTAGE (IDEA-19, 20, 21).

`moteur_execution_prod` applique déjà des frais versionnés et un VWAP de profondeur. Ce qui manquait :

  • IDEA-19 : chaque composante de coût porte un STATUT explicite — KNOWN / NOT_APPLICABLE / UNMEASURABLE.
    Une composante inconnue n'est JAMAIS traitée comme zéro : elle bloque la promotion (deny-by-default).
  • IDEA-20 : chaque composante déclare `source`, `methode` et `included_in_price`. Un coût déjà contenu
    dans le prix exécutable (le spread payé dans le VWAP) n'est PAS soustrait une deuxième fois.
  • IDEA-21 : la capacité round-trip est limitée par la JAMBE LA PLUS RESTRICTIVE (entrée ou sortie).

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

#: composantes de coût attendues (IDEA-19). `borrow_carry` n'est applicable que sur certains produits.
COMPOSANTES = ("fees", "spread", "slippage", "impact", "funding", "latency", "adverse_selection", "borrow_carry")

KNOWN = "KNOWN"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNMEASURABLE = "UNMEASURABLE"
STATUTS = (KNOWN, NOT_APPLICABLE, UNMEASURABLE)


def composante(valeur_bps=None, *, statut: str = UNMEASURABLE, source: str | None = None,
               methode: str | None = None, included_in_price: bool = False) -> dict:
    """Déclare UNE composante de coût. `included_in_price=True` signifie que ce coût est DÉJÀ dans le prix
    exécutable (VWAP) : il sera compté pour information mais jamais soustrait une seconde fois (IDEA-20)."""
    s = str(statut).upper()
    if s not in STATUTS:
        raise ValueError("statut de cout inconnu: %s" % statut)
    v = None
    if valeur_bps is not None:
        try:
            v = float(valeur_bps)
        except (TypeError, ValueError):
            v = None
    if s == KNOWN and v is None:
        raise ValueError("une composante KNOWN doit porter une valeur")
    return {"valeur_bps": v, "statut": s, "source": source, "methode": methode,
            "included_in_price": bool(included_in_price)}


def additionner_couts(couts: dict) -> dict:
    """IDEA-19 + IDEA-20 — total des coûts À SOUSTRAIRE (hors composantes déjà dans le prix), avec la liste
    des composantes UNMEASURABLE qui interdisent la promotion. Aucune composante inconnue n'est comptée 0."""
    total, deja_dans_prix, inconnues, detail = 0.0, 0.0, [], {}
    for nom in COMPOSANTES:
        c = (couts or {}).get(nom)
        if c is None:
            inconnues.append(nom)                            # absente = inconnue, PAS gratuite
            detail[nom] = {"statut": UNMEASURABLE, "valeur_bps": None}
            continue
        if not isinstance(c, dict) or "statut" not in c:
            raise ValueError("composante %s mal declaree (utiliser composante())" % nom)
        detail[nom] = c
        if c["statut"] == UNMEASURABLE:
            inconnues.append(nom)
        elif c["statut"] == KNOWN:
            v = float(c.get("valeur_bps") or 0.0)
            if c.get("included_in_price"):
                deja_dans_prix += v                          # compté pour info, jamais re-soustrait
            else:
                total += v
    return {"cout_a_soustraire_bps": round(total, 6),
            "deja_inclus_dans_le_prix_bps": round(deja_dans_prix, 6),
            "composantes_inconnues": inconnues,
            "complet": not inconnues,                        # deny-by-default : incomplet = non promouvable
            "promotion_autorisee": not inconnues,
            "detail": detail}


def net_apres_couts(gross_bps: float, couts: dict) -> dict:
    """Net = brut − coûts NON déjà inclus dans le prix. Si une composante est UNMEASURABLE, le net est rendu
    mais marqué NON PROMOUVABLE : on ne maquille pas un trou en zéro."""
    agg = additionner_couts(couts)
    try:
        brut = float(gross_bps)
    except (TypeError, ValueError):
        return {"net_bps": None, "statut": "GROSS_INVALIDE", "promotion_autorisee": False, **agg}
    net = brut - agg["cout_a_soustraire_bps"]
    return {"gross_bps": round(brut, 6), "net_bps": round(net, 6),
            "statut": (KNOWN if agg["complet"] else UNMEASURABLE),
            "promotion_autorisee": agg["promotion_autorisee"],
            "cout_a_soustraire_bps": agg["cout_a_soustraire_bps"],
            "deja_inclus_dans_le_prix_bps": agg["deja_inclus_dans_le_prix_bps"],
            "composantes_inconnues": agg["composantes_inconnues"]}


def capacite_round_trip(capacite_entree_usd, capacite_sortie_usd) -> dict:
    """IDEA-21 — la capacité d'un aller-retour est celle de la JAMBE LA PLUS RESTRICTIVE. Si une jambe est
    inconnue, la capacité round-trip est inconnue (jamais celle de l'autre jambe par optimisme)."""
    def _v(x):
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        return v if v == v and v >= 0 else None
    e, s = _v(capacite_entree_usd), _v(capacite_sortie_usd)
    if e is None or s is None:
        return {"capacite_usd": None, "jambe_limitante": None, "statut": UNMEASURABLE,
                "motif": "capacite d'une jambe inconnue"}
    cap = min(e, s)
    return {"capacite_usd": round(cap, 6), "jambe_limitante": ("entree" if e <= s else "sortie"),
            "statut": (KNOWN if cap > 0 else NOT_APPLICABLE),
            "capacite_entree_usd": e, "capacite_sortie_usd": s}


def courbe_capacite_nette(courbe) -> dict:
    """IDEA-21 — à partir d'une courbe [(notional, net_bps)], rend le notionnel maximal encore rentable
    (net > 0) et signale l'effondrement. Une courbe vide rend None, pas 0."""
    pts = []
    for p in (courbe or []):
        if isinstance(p, dict):
            n, net = p.get("notional_usd", p.get("notional")), p.get("net_bps")
        else:
            n, net = (list(p) + [None, None])[:2]
        try:
            pts.append((float(n), float(net)))
        except (TypeError, ValueError):
            continue
    pts.sort()
    if not pts:
        return {"notional_max_rentable_usd": None, "statut": UNMEASURABLE, "points": []}
    rentables = [n for n, net in pts if net > 0]
    return {"notional_max_rentable_usd": (max(rentables) if rentables else None),
            "statut": (KNOWN if rentables else NOT_APPLICABLE),
            "capacite_non_nulle": bool(rentables),
            "points": [{"notional_usd": n, "net_bps": round(net, 4)} for n, net in pts]}


__all__ = ["COMPOSANTES", "KNOWN", "NOT_APPLICABLE", "UNMEASURABLE", "STATUTS", "composante",
           "additionner_couts", "net_apres_couts", "capacite_round_trip", "courbe_capacite_nette"]
