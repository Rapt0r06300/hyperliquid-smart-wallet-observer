"""[COPY-VAULT lot2 #42] EQUITY ET POSITIONS LUES EN PARALLÈLE : récupérer equity et positions EN PARALLÈLE plutôt
que séquentiellement quand la lecture séquentielle ajoute de la latence. En séquentiel, la latence s'additionne
(equity PUIS positions) ; en parallèle, elle est celle de la plus lente. Moins de latence = état plus frais.
Pur, 0 réseau, 0 ordre réel (modélisation de latence).
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def latence_lecture(*, latence_equity_ms: Any, latence_positions_ms: Any, parallele: bool = True) -> dict[str, Any]:
    """Parallèle → max(equity, positions) ; séquentiel → somme. Latences invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (latence_equity_ms, latence_positions_ms)):
        return {"latence_ms": UNMEASURABLE, "raison": "LATENCE_INVALIDE"}
    e, p = float(latence_equity_ms), float(latence_positions_ms)
    if parallele:
        return {"latence_ms": round(max(e, p), 3), "mode": "PARALLELE",
                "gain_ms": round((e + p) - max(e, p), 3)}
    return {"latence_ms": round(e + p, 3), "mode": "SEQUENTIEL", "gain_ms": 0.0}


__all__ = ["latence_lecture", "UNMEASURABLE"]
