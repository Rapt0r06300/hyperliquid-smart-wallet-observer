"""[COPY-VAULT pépite 284] FEE-DRAG RATIO : leader_fees / leader_gross_trading_edge. Un leader dont l'edge
brut (avant frais) est proche de zéro est une MAUVAISE cible de réplication : ses frais mangent tout, et une
fois nos propres coûts ajoutés on copie une perte. Ratio ≥ 1 → l'edge net est nul ou négatif. Edge brut ≤ 0 →
UNMEASURABLE (rien à répliquer). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def fee_drag(fees: Any, edge_brut: Any) -> dict[str, Any]:
    """ratio = fees / edge_brut. edge_brut ≤ 0 → UNMEASURABLE (pas d'edge à répliquer, mauvaise cible).
    ratio ≥ 1 → mauvaise cible (frais ≥ edge brut). Sinon cible potentiellement viable (edge net > 0)."""
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
               for x in (fees, edge_brut)):
        return {"ratio": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    if edge_brut <= 0:
        return {"ratio": UNMEASURABLE, "mauvaise_cible": True, "raison": "EDGE_BRUT_NON_POSITIF"}
    if fees < 0:
        return {"ratio": UNMEASURABLE, "raison": "FEES_NEGATIF"}
    ratio = float(fees) / float(edge_brut)
    return {"ratio": round(ratio, 6), "mauvaise_cible": ratio >= 1.0,
            "edge_net_estime": round(float(edge_brut) - float(fees), 8)}


__all__ = ["fee_drag", "UNMEASURABLE"]
