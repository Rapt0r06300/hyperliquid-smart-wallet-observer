"""[COPY-VAULT #74] PER-VAULT REPLICATION SHORTFALL : mesurer, PAR VAULT, l'écart entre ce que le leader a gagné
après son fill et ce que NOTRE copie a gagné après nos coûts : leader_return_after_fill − our_copy_return_after_costs.
C'est le vrai « coût de réplication » d'un vault : un leader rentable qu'on ne réplique pas fidèlement peut nous
faire perdre. Donnée manquante → UNMEASURABLE. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
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


def shortfall_attribution_receipt(
    *, leader_return_bps: Any, our_return_after_costs_bps: Any,
    cost_bps: Any, latency_bps: Any, capacity_bps: Any, tolerance_bps: float = 1e-6
) -> dict[str, Any]:
    """Require the measured shortfall to reconcile to cost, latency and capacity."""
    values = (leader_return_bps, our_return_after_costs_bps, cost_bps, latency_bps, capacity_bps, tolerance_bps)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
        return {"status": UNMEASURABLE, "reason": "non_finite_shortfall_observation"}
    components = (cost_bps, latency_bps, capacity_bps)
    if any(value < 0 for value in components) or tolerance_bps < 0:
        return {"status": UNMEASURABLE, "reason": "invalid_attribution_components"}
    measured = float(leader_return_bps) - float(our_return_after_costs_bps)
    attributed = sum(float(value) for value in components)
    reconciled = math.isclose(measured, attributed, abs_tol=float(tolerance_bps))
    return {"status": "PROVEN" if reconciled else "UNMEASURABLE", "measured_shortfall_bps": round(measured, 8),
            "attributed_shortfall_bps": round(attributed, 8), "reconciled": reconciled,
            "components": {"cost_bps": float(cost_bps), "latency_bps": float(latency_bps), "capacity_bps": float(capacity_bps)}}


__all__ = ["shortfall", "shortfall_attribution_receipt", "UNMEASURABLE"]
