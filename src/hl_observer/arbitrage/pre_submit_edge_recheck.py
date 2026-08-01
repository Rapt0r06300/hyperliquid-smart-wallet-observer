"""[ARB #21] PRE-SUBMIT EDGE RECHECK : recalculer le net edge JUSTE AVANT l'envoi simulé de chaque décision,
pas seulement à la détection. Entre la détection et l'envoi, le marché a pu bouger ; un edge évaporé ne doit
pas être exécuté. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def recheck_avant_envoi(edge_detection_bps: Any, edge_courant_bps: Any, *, seuil_net_bps: float) -> dict[str, Any]:
    """Autorise l'envoi seulement si l'edge RECALCULÉ à l'instant de l'envoi reste ≥ seuil. Rapporte la
    dégradation depuis la détection. Edge courant non mesurable → on n'envoie pas (prudence)."""
    if not isinstance(edge_courant_bps, (int, float)):
        return {"envoyer": False, "raison": "EDGE_COURANT_NON_MESURABLE"}
    degr = (round(float(edge_detection_bps) - float(edge_courant_bps), 4)
            if isinstance(edge_detection_bps, (int, float)) else None)
    ok = float(edge_courant_bps) >= float(seuil_net_bps)
    return {"envoyer": bool(ok), "edge_courant_bps": round(float(edge_courant_bps), 4),
            "degradation_bps": degr, "seuil_net_bps": float(seuil_net_bps),
            "raison": ("OK" if ok else "EDGE_EVAPORE_AVANT_ENVOI")}


__all__ = ["recheck_avant_envoi"]
