"""[ARB #31] FILLED-QUANTITY HEDGE : la jambe opposée est dimensionnée sur la quantité RÉELLEMENT remplie de la
première jambe, jamais sur la quantité initialement DEMANDÉE. Hedger la quantité demandée alors que seule une
fraction a été remplie crée une sur-couverture (nouvelle exposition nue de sens inverse). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def taille_hedge(qte_remplie: Any, *, qte_demandee: Any = None) -> dict[str, Any]:
    """Taille de la jambe de couverture = quantité remplie (bornée à la demandée). Remplie inconnue → UNMEASURABLE
    (on ne hedge JAMAIS une quantité supposée)."""
    if not isinstance(qte_remplie, (int, float)) or float(qte_remplie) < 0:
        return {"qte_hedge": UNMEASURABLE, "raison": "FILL_INCONNU"}
    q = float(qte_remplie)
    borne = None
    if isinstance(qte_demandee, (int, float)):
        borne = float(qte_demandee)
        q = min(q, borne)                                # ne jamais hedger plus que ce qui a été demandé
    return {"qte_hedge": round(q, 12),
            "sur_demande": bool(borne is not None and float(qte_remplie) > borne),
            "base": "quantite_remplie"}


__all__ = ["taille_hedge", "UNMEASURABLE"]
