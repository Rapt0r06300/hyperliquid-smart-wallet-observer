"""[COPY-VAULT lot2 #51] VERSION METADATA DU COIN PAR FILL : attacher à CHAQUE fill le tick size / lot size /
min notional / status utilisés AU MOMENT EXACT du fill. Ces paramètres changent (une venue ajuste la précision) ;
figer ceux en vigueur au fill rend la réplication et l'audit exacts a posteriori, sans les recalculer avec des
paramètres actuels qui ont peut-être changé. Metadata incomplète → refus. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_REQUIS = ("tick_size", "lot_size", "min_notional", "status")


def attacher(fill: Any, *, tick_size: Any, lot_size: Any, min_notional: Any, status: Any) -> dict[str, Any]:
    """Attache la metadata du coin au fill. Un champ requis manquant/invalide → refus (on ne fige pas une
    metadata partielle qui fausserait la reconstruction)."""
    meta = {"tick_size": tick_size, "lot_size": lot_size, "min_notional": min_notional, "status": status}
    manquants = [k for k in _REQUIS[:3] if not isinstance(meta[k], (int, float))]
    if not status:
        manquants.append("status")
    if manquants:
        return {"ok": False, "manquants": manquants, "raison": "METADATA_INCOMPLETE"}
    return {"ok": True, "fill": fill, "metadata": {**meta, "status": str(status).upper()}, "fige": True}


__all__ = ["attacher"]
