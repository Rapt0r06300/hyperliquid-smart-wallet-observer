"""[COPY-VAULT #66] HARD REDUCE-ONLY INVARIANT : une réduction copiée ne doit MATHÉMATIQUEMENT jamais augmenter
l'exposition paper. |position_après| ≤ |position_avant|, et le signe ne s'inverse pas (une réduction ne flippe
pas). L'invariant est vérifié en dur : toute réduction qui violerait cela est bornée et signalée. Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
_TOL = 1e-12


def appliquer_reduction(position_avant: Any, quantite_reduction: Any) -> dict[str, Any]:
    """Réduit |position| de la quantité demandée, bornée à la taille détenue (jamais au-delà de 0 ni flip).
    Garantit |après| ≤ |avant|. Entrées invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (position_avant, quantite_reduction)):
        return {"position": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    avant = float(position_avant)
    q = abs(float(quantite_reduction))
    reduction_effective = min(q, abs(avant))            # ne jamais réduire plus que ce qui est détenu
    signe = 1.0 if avant >= 0 else -1.0
    apres = signe * (abs(avant) - reduction_effective)
    # invariant dur : |après| ne peut pas dépasser |avant|
    if abs(apres) > abs(avant) + _TOL:
        return {"position": round(avant, 12), "violation": True, "raison": "INVARIANT_REDUCE_ONLY_VIOLE"}
    return {"position": round(apres, 12), "reduction_effective": round(reduction_effective, 12),
            "violation": False, "invariant_ok": True}


__all__ = ["appliquer_reduction", "UNMEASURABLE"]
