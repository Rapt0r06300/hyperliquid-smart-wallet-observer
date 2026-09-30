"""[ARB #43] GAP-RISK BUDGET : mesurer le déplacement de prix MAXIMUM tolérable pendant le délai entre la jambe 1
et la jambe 2. Tant que le hedge n'est pas posé, on est exposé ; le budget = combien le marché peut bouger avant
que l'edge attendu soit mangé. Un budget non chiffrable (edge inconnu) → UNMEASURABLE. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def budget_bps(edge_attendu_bps: Any, *, fraction_tolerable: float = 1.0) -> Any:
    """Budget de gap = fraction de l'edge attendu qu'on accepte de risquer avant hedge. Edge ≤ 0 ou inconnu →
    UNMEASURABLE (pas de budget si pas d'edge à protéger)."""
    if not isinstance(edge_attendu_bps, (int, float)) or float(edge_attendu_bps) <= 0:
        return UNMEASURABLE
    return round(float(edge_attendu_bps) * max(0.0, min(1.0, float(fraction_tolerable))), 4)


def depasse_budget(mouvement_bps: Any, edge_attendu_bps: Any, *, fraction_tolerable: float = 1.0) -> dict[str, Any]:
    """Le mouvement défavorable observé pendant le délai dépasse-t-il le budget ? Inconnu → dépassement présumé
    (fail-closed : on ne suppose jamais que le marché est resté sage)."""
    b = budget_bps(edge_attendu_bps, fraction_tolerable=fraction_tolerable)
    if b == UNMEASURABLE or not isinstance(mouvement_bps, (int, float)):
        return {"depasse": True, "budget_bps": b, "raison": "NON_CHIFFRABLE_FAIL_CLOSED"}
    depasse = float(mouvement_bps) > float(b)
    return {"depasse": bool(depasse), "budget_bps": b, "mouvement_bps": float(mouvement_bps),
            "raison": ("BUDGET_DEPASSE" if depasse else "DANS_LE_BUDGET")}


__all__ = ["budget_bps", "depasse_budget", "UNMEASURABLE"]
