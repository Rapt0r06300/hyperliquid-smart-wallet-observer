"""[DATA lot2 #30] PERIODIC BOOK RE-SNAPSHOT : re-snapshoter périodiquement le carnet MÊME sans gap apparent, pour
effacer la dérive cumulative locale (petites erreurs d'application de deltas qui s'accumulent). Un carnet « qui a
l'air bon » peut avoir dérivé silencieusement (Cryptofeed le fait sur Binance). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def doit_resnapshot(dernier_snapshot_ms: Any, now_ms: Any, *, intervalle_ms: float) -> dict[str, Any]:
    """Vrai si l'intervalle depuis le dernier snapshot est écoulé. Horodatage inconnu → resnapshot (prudence :
    on ne fait pas confiance à un carnet dont on ignore l'âge)."""
    if not all(isinstance(x, (int, float)) for x in (dernier_snapshot_ms, now_ms)):
        return {"resnapshot": True, "raison": "HORODATAGE_INCONNU"}
    age = float(now_ms) - float(dernier_snapshot_ms)
    if age >= float(intervalle_ms):
        return {"resnapshot": True, "age_ms": round(age, 3), "raison": "INTERVALLE_ECOULE"}
    return {"resnapshot": False, "age_ms": round(age, 3), "reste_ms": round(float(intervalle_ms) - age, 3)}


__all__ = ["doit_resnapshot"]
