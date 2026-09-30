"""[COPY-VAULT pépite 294] FLAT-BOUNDARY INVARIANT : à la fermeture de la position source, la somme algébrique
des deltas de l'epoch (achats positifs, ventes négatives) doit revenir à ZÉRO dans la tolérance de précision.
Si le résidu n'est pas nul, c'est qu'un fill a été manqué, dupliqué ou mal signé — l'état de position est faux
et il ne faut pas s'y fier. C'est un contrôle de bouclage dur du cycle FLAT→...→FLAT. Deltas non finis →
fail-closed. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

OK = "OK"
VIOLATION = "VIOLATION"


def verifier(deltas: list[Any], *, tolerance: float = 1e-9) -> dict[str, Any]:
    """Somme des deltas de l'epoch. |somme| ≤ tolerance → invariant respecté (position bien revenue à plat).
    Sinon → VIOLATION (résidu = fill manqué/dupliqué/mal signé). Un delta non fini invalide tout (fail-closed).
    Liste vide → VIOLATION (un epoch fermé sans aucun delta est incohérent)."""
    if not deltas:
        return {"etat": VIOLATION, "somme": None, "raison": "AUCUN_DELTA"}
    total = 0.0
    for d in deltas:
        if not (isinstance(d, (int, float)) and not isinstance(d, bool) and math.isfinite(d)):
            return {"etat": VIOLATION, "somme": None, "raison": "DELTA_NON_FINI"}
        total += float(d)
    ok = abs(total) <= tolerance
    return {"etat": OK if ok else VIOLATION, "somme": round(total, 12),
            "raison": None if ok else "RESIDU_NON_NUL"}


__all__ = ["verifier", "OK", "VIOLATION"]
