"""[ARB #44] EMERGENCY RESIDUAL POLICY : si, pendant qu'une jambe est orpheline, le marché dépasse le budget de
gap-risk (#43), la priorité passe à la RÉDUCTION DU RISQUE (déboucler maintenant) plutôt qu'à la conservation du
spread attendu (attendre un meilleur prix). Espérer que ça revienne, c'est transformer un arb en pari. Pur,
0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.arbitrage.gap_risk_budget import depasse_budget

REDUIRE_RISQUE = "REDUIRE_RISQUE"      # déboucler tout de suite, au prix du marché
CONSERVER_SPREAD = "CONSERVER_SPREAD"  # rester exposé pour capter le spread attendu


def politique(mouvement_bps: Any, edge_attendu_bps: Any, *, fraction_tolerable: float = 1.0) -> dict[str, Any]:
    """Budget dépassé (ou non chiffrable) → REDUIRE_RISQUE ; sinon on peut encore CONSERVER_SPREAD."""
    d = depasse_budget(mouvement_bps, edge_attendu_bps, fraction_tolerable=fraction_tolerable)
    action = REDUIRE_RISQUE if d["depasse"] else CONSERVER_SPREAD
    return {"action": action, "budget_bps": d["budget_bps"], "raison": d["raison"],
            "priorite_risque": bool(d["depasse"])}


__all__ = ["politique", "REDUIRE_RISQUE", "CONSERVER_SPREAD"]
