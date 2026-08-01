"""[ARB lot2 #5] IOC POUR LA JAMBE DE HEDGE : la jambe de couverture est envoyée en IOC (Immediate-Or-Cancel) —
ce qui se remplit immédiatement se remplit, le RELIQUAT est annulé, JAMAIS transformé en ordre passif involontaire.
Un reliquat passif de hedge, c'est une exposition résiduelle non désirée qui traîne. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def simuler_ioc(qte_demandee: Any, qte_disponible_immediate: Any) -> dict[str, Any]:
    """Remplit min(demandée, disponible immédiate) ; le reliquat est ANNULÉ (jamais laissé passif). Entrées
    invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (qte_demandee, qte_disponible_immediate)) \
            or float(qte_demandee) < 0 or float(qte_disponible_immediate) < 0:
        return {"remplie": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    remplie = min(float(qte_demandee), float(qte_disponible_immediate))
    reliquat = float(qte_demandee) - remplie
    return {"remplie": round(remplie, 12), "reliquat_annule": round(reliquat, 12),
            "reste_passif": 0.0, "partiel": bool(reliquat > 1e-12)}


__all__ = ["simuler_ioc", "UNMEASURABLE"]
