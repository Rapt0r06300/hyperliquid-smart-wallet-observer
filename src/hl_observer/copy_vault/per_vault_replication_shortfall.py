"""[COPY-VAULT #74] PER-VAULT REPLICATION SHORTFALL : mesurer, PAR VAULT, l'écart entre ce que le leader a gagné
après son fill et ce que NOTRE copie a gagné après nos coûts : leader_return_after_fill − our_copy_return_after_costs.
C'est le vrai « coût de réplication » d'un vault : un leader rentable qu'on ne réplique pas fidèlement peut nous
faire perdre. Donnée manquante → UNMEASURABLE. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def shortfall(leader_return_bps: Any, notre_return_apres_couts_bps: Any) -> dict[str, Any]:
    """Shortfall = leader_return − notre_return_après_coûts (bps). >0 = on capte moins que le leader.
    Une des deux valeurs manquante → UNMEASURABLE (jamais supposer une réplication parfaite)."""
    if not all(isinstance(x, (int, float)) for x in (leader_return_bps, notre_return_apres_couts_bps)):
        return {"shortfall_bps": UNMEASURABLE, "raison": "RENDEMENT_MANQUANT"}
    sf = float(leader_return_bps) - float(notre_return_apres_couts_bps)
    return {"shortfall_bps": round(sf, 4), "capte_moins": bool(sf > 0),
            "fidelite_bps": round(float(notre_return_apres_couts_bps), 4)}


__all__ = ["shortfall", "UNMEASURABLE"]
