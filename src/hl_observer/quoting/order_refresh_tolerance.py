"""[CROSS-VENUE lot2 #80] ORDER-REFRESH TOLERANCE : ne pas PERDRE une bonne position de file pour améliorer le prix
de 0,1 tick économiquement inutile. Un refresh détruit la priorité acquise dans la queue ; il ne se justifie que si
le gain de prix dépasse une tolérance minimale (Hummingbot implémente cette tolérance). Sous la tolérance → HOLD.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def doit_refresh(prix_actuel: Any, prix_cible: Any, *, tick: float, min_ticks: float = 1.0) -> dict[str, Any]:
    """Refresh autorisé seulement si |cible − actuel| ≥ min_ticks × tick (gain de prix significatif). Sinon on
    garde l'ordre (et sa position de file). Prix/tick invalide → HOLD (on ne détruit pas la queue à l'aveugle)."""
    if not all(isinstance(x, (int, float)) for x in (prix_actuel, prix_cible)) or not (isinstance(tick, (int, float)) and tick > 0):
        return {"refresh": False, "raison": "NON_MESURABLE_HOLD"}
    gain_ticks = abs(float(prix_cible) - float(prix_actuel)) / float(tick)
    ok = gain_ticks >= float(min_ticks)
    return {"refresh": bool(ok), "gain_ticks": round(gain_ticks, 4), "min_ticks": float(min_ticks),
            "raison": ("GAIN_SIGNIFICATIF" if ok else "SOUS_TOLERANCE_GARDER_QUEUE")}


__all__ = ["doit_refresh"]
