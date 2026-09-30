"""S4 — DÉTECTION DE CROWDING / SATURATION D'EDGE dans le temps.

Notre edge se fait-il arbitrer ? On compare l'edge RÉCENT à l'edge HISTORIQUE : s'il s'érode, la
piste se sature (d'autres arrivent) -> réduire/retirer AVANT qu'il meure. Deny-by-default. PAPER only.
"""
from __future__ import annotations

SEUIL_SATURATION = 0.5      # edge recent < 50% de l'historique = saturation


def saturation(edge_historique_bps: float, edge_recent_bps: float, *, seuil: float = SEUIL_SATURATION) -> dict | None:
    """{ratio, sature}. Historique <= 0 -> non mesurable (pas d'edge de référence)."""
    h = float(edge_historique_bps)
    if h <= 0:
        return None
    ratio = float(edge_recent_bps) / h
    return {"ratio": round(ratio, 4), "sature": ratio < float(seuil)}


__all__ = ["SEUIL_SATURATION", "saturation"]
