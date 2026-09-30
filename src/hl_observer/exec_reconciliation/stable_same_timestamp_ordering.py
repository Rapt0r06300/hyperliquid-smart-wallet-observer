"""[EXEC pépite 215] STABLE SAME-TIMESTAMP ORDERING : plusieurs événements portant EXACTEMENT le même timestamp
doivent être ordonnés par un numéro de séquence DÉTERMINISTE (tie-breaker), sinon leur ordre relatif est instable et
certains peuvent « disparaître » au tri (bug corrigé dans Nautilus). On trie par (timestamp, seq) — total et stable.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def trier(evenements: Iterable[Any]) -> dict[str, Any]:
    """Trie les événements {ts, seq, ...} par (ts, seq) — ordre TOTAL déterministe. Un événement sans ts ou seq
    valide est rejeté (non ordonnable de façon stable) plutôt que placé au hasard."""
    valides, rejetes = [], 0
    for e in evenements:
        ts, seq = (e or {}).get("ts"), (e or {}).get("seq")
        if isinstance(ts, (int, float)) and isinstance(seq, (int, float)):
            valides.append(e)
        else:
            rejetes += 1
    ordonnes = sorted(valides, key=lambda e: (float(e["ts"]), int(e["seq"])))
    return {"ordonnes": ordonnes, "n": len(ordonnes), "rejetes": rejetes}


__all__ = ["trier"]
