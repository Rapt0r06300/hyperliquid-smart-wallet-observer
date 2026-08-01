"""[CROSS-VENUE lot2 #89] BATCH-SUBMIT DE PLUSIEURS COUCHES MAKER : soumettre EN BATCH plusieurs couches maker
indépendantes calculées sur le MÊME état de marché, avec un TIMESTAMP PARTAGÉ. Soumettre les couches une par une les
calcule sur des états légèrement différents (le marché bouge entre deux) et brouille l'attribution ; un batch à
timestamp commun garantit qu'elles reflètent le même instant. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def preparer_batch(couches: Sequence[Any], *, ts_ms: Any, snapshot_id: Any) -> dict[str, Any]:
    """Estampille toutes les couches valides avec le MÊME ts et le même snapshot_id. Couche invalide (prix/taille)
    ignorée. ts/snapshot manquant → batch refusé (on ne soumet pas un batch non horodaté)."""
    if not isinstance(ts_ms, (int, float)) or snapshot_id is None:
        return {"ok": False, "raison": "TS_OU_SNAPSHOT_MANQUANT"}
    valides = []
    for c in couches:
        prix, taille = (c or {}).get("prix"), (c or {}).get("taille")
        if isinstance(prix, (int, float)) and isinstance(taille, (int, float)) and float(taille) > 0:
            valides.append({"prix": float(prix), "taille": float(taille),
                            "ts_ms": float(ts_ms), "snapshot_id": snapshot_id})
    return {"ok": bool(valides), "couches": valides, "n": len(valides),
            "ts_partage_ms": float(ts_ms), "snapshot_id": snapshot_id}


__all__ = ["preparer_batch"]
