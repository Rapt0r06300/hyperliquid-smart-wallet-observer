from __future__ import annotations

from dataclasses import dataclass

from hl_observer.simulation.decision_replay_analyzer import ReplayAnalysis


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

