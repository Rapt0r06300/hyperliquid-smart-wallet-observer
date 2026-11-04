from __future__ import annotations

from dataclasses import dataclass

from hl_observer.simulation.decision_replay_analyzer import ReplayAnalysis
from hl_observer.simulation.cost_components import slippage_bps as _slippage_bps
from hl_observer.simulation.cost_components import spread_bps as _spread_bps


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    total_fees_usdc: float
    average_copy_degradation_bps: float | None
    max_copy_degradation_bps: float | None
    negative_pnl_after_costs: bool
    notes: tuple[str, ...]


def build_cost_breakdown(analysis: ReplayAnalysis) -> CostBreakdown:
    degradations = [
        event.copy_degradation_bps
        for event in analysis.events
        if event.copy_degradation_bps is not None
    ]
    notes: list[str] = []
    if analysis.total_fees_usdc > 0:
        notes.append("FEES_DRAG: les frais reduisent le PnL simule.")
    if degradations and max(degradations) >= 20:
        notes.append("COPY_DEGRADATION_COST: la copie arrive avec couts/latence sensibles.")
    if analysis.total_estimated_pnl_usdc < 0 and analysis.total_fees_usdc > abs(analysis.total_estimated_pnl_usdc) * 0.2:
        notes.append("COSTS_DOMINATE_SMALL_EDGE: les couts mangent une part importante du resultat.")
    return CostBreakdown(
        total_fees_usdc=analysis.total_fees_usdc,
        average_copy_degradation_bps=round(sum(degradations) / len(degradations), 6) if degradations else None,
        max_copy_degradation_bps=max(degradations) if degradations else None,
        negative_pnl_after_costs=analysis.total_estimated_pnl_usdc < 0,
        notes=tuple(notes),
    )


def format_cost_breakdown(costs: CostBreakdown) -> str:
    lines = [
        "cost_breakdown=local_simulation",
        f"total_fees_usdc={costs.total_fees_usdc:.6f}",
        f"average_copy_degradation_bps={costs.average_copy_degradation_bps}",
        f"max_copy_degradation_bps={costs.max_copy_degradation_bps}",
        f"negative_pnl_after_costs={str(costs.negative_pnl_after_costs).lower()}",
    ]
    lines.extend(f"note={note}" for note in costs.notes)
    return "\n".join(lines)


def spread_not_double_counted_receipt(
    *, mid_decision: object, best_touch: object, avg_fill_price: object, side: object
) -> dict[str, object]:
    """Check that spread plus depth impact equals the single mid-to-fill cost."""
    try:
        mid = float(mid_decision)
        touch = float(best_touch)
        fill = float(avg_fill_price)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "PRICE_OBSERVATION_INVALID"}
    if any(not __import__("math").isfinite(value) or value <= 0 for value in (mid, touch, fill)):
        return {"status": "UNMEASURABLE", "reason": "PRICE_OBSERVATION_INVALID"}
    spread = _spread_bps(mid, touch, side)
    slippage = _slippage_bps(touch, fill, side, mid=mid)
    direction = 1.0 if str(side).upper() in {"BUY", "B", "LONG", "BID"} else -1.0 if str(side).upper() in {"SELL", "S", "SHORT", "ASK"} else 0.0
    direct = direction * (fill - mid) / mid * 10_000.0 if direction else None
    if spread is None or slippage is None or direct is None:
        return {"status": "UNMEASURABLE", "reason": "SIDE_OR_COST_COMPONENT_INVALID"}
    reconciles = abs((spread + slippage) - direct) <= 1e-5
    return {"status": "PROVEN" if reconciles else "REJECTED", "spread_bps": spread, "slippage_bps": slippage, "mid_to_fill_bps": round(direct, 6), "spread_count": 1, "reconciles": reconciles}

