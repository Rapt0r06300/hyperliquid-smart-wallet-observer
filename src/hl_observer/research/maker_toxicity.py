"""ALPHA P23 — TOXICITÉ maker : prédire la sélection adverse AVANT de poster. Maker seulement si E[PnL|fill]>0.

Un fill maker « gratuit » est souvent toxique : on est rempli précisément quand le marché tourne contre nous.
On estime une toxicité ∈ [0,1] depuis flux agressif / absorption / fragilité de liquidité / épuisement de
queue / tilt microprix / régime de spread, puis on n'autorise le maker que si l'espérance de PnL sachant
fill reste positive après coûts. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _c01(x: float) -> float:
    return max(0.0, min(1.0, x))


def toxicity_score(*, aggr_flow_norm: Any = None, absorption: Any = None, queue_depletion: Any = None,
                   microprice_tilt_bps: Any = None, spread_widening: Any = None) -> dict[str, Any]:
    """Score de toxicité ∈ [0,1]. Plus c'est haut, plus le fill maker sera adverse. UNMEASURABLE si tout absent."""
    parts = []
    if isinstance(aggr_flow_norm, (int, float)):
        parts.append(_c01(aggr_flow_norm))
    if isinstance(absorption, (int, float)):
        parts.append(_c01(absorption))
    if isinstance(queue_depletion, (int, float)):
        parts.append(_c01(queue_depletion))
    if isinstance(microprice_tilt_bps, (int, float)):
        parts.append(_c01(abs(microprice_tilt_bps) / 5.0))
    if isinstance(spread_widening, (int, float)):
        parts.append(_c01(spread_widening))
    if not parts:
        return {"toxicity": UNMEASURABLE}
    return {"toxicity": round(sum(parts) / len(parts), 4), "n_composantes": len(parts)}


def esperance_pnl_fill_bps(edge_brut_bps: float, toxicity: Any, *, spread_capture_bps: float,
                           maker_fee_bps: float) -> Any:
    """E[PnL|fill] = capture spread − frais maker − toxicity × edge_brut (perte adverse). UNMEASURABLE si toxicity absent."""
    if not isinstance(toxicity, (int, float)):
        return UNMEASURABLE
    return round(spread_capture_bps - maker_fee_bps - toxicity * abs(edge_brut_bps), 4)


def maker_autorise(e_pnl_fill_bps: Any) -> bool:
    """Maker autorisé seulement si E[PnL|fill] > 0 (jamais 'price touched = fill')."""
    return isinstance(e_pnl_fill_bps, (int, float)) and e_pnl_fill_bps > 0


__all__ = ["toxicity_score", "esperance_pnl_fill_bps", "maker_autorise", "UNMEASURABLE"]
