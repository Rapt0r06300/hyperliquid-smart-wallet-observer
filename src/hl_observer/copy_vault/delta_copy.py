"""[COPY-VAULT #64] DELTA-COPY : copier le CHANGEMENT réellement produit par le fill (position_après −
position_avant), jamais reconstruire naïvement toute la position à chaque événement. Reconstruire à chaque fill
re-copie une exposition déjà répliquée → double comptage. Le delta est la seule quantité à répliquer. Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def delta(position_avant: Any, position_apres: Any) -> dict[str, Any]:
    """Delta signé = après − avant. C'est CE qu'il faut copier, pas `position_apres`. Entrées invalides →
    UNMEASURABLE (on ne devine pas un changement)."""
    if not all(isinstance(x, (int, float)) for x in (position_avant, position_apres)):
        return {"delta": UNMEASURABLE, "raison": "POSITION_INCONNUE"}
    d = float(position_apres) - float(position_avant)
    sens = "AUCUN" if abs(d) <= 1e-12 else ("ACHAT" if d > 0 else "VENTE")
    return {"delta": round(d, 12), "sens": sens, "a_copier": round(d, 12),
            "note": "copier le delta, pas la position entiere"}


def appliquer_delta(notre_position: Any, delta_a_copier: Any) -> dict[str, Any]:
    """Applique le delta à NOTRE position paper. Entrées invalides → UNMEASURABLE (pas de mutation à l'aveugle)."""
    if not all(isinstance(x, (int, float)) for x in (notre_position, delta_a_copier)):
        return {"position": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    return {"position": round(float(notre_position) + float(delta_a_copier), 12)}


__all__ = ["delta", "appliquer_delta", "UNMEASURABLE"]
