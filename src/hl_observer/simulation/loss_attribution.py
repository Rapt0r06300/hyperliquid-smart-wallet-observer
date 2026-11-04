from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from hl_observer.simulation.cost_breakdown import CostBreakdown, build_cost_breakdown, format_cost_breakdown
from hl_observer.simulation.decision_replay_analyzer import ReplayAnalysis, analyze_decision_logs, format_replay_analysis
from hl_observer.simulation.pnl_attribution import PnlAttribution, build_pnl_attribution, format_pnl_attribution
from hl_observer.simulation.root_cause import RootCauseReport, classify_root_causes, format_root_cause_report


@dataclass(frozen=True, slots=True)
class LossAttributionReport:
    analysis: ReplayAnalysis
    costs: CostBreakdown
    pnl: PnlAttribution
    root_causes: RootCauseReport


def reconcile_copy_loss_components(
    *,
    gross_pnl_usd: object,
    net_pnl_usd: object,
    delay_usd: object,
    spread_usd: object,
    fees_usd: object,
    funding_usd: object,
    capacity_usd: object,
    tolerance: float = 1e-9,
) -> dict[str, object]:
    """Reconcile leader/copy loss components without hiding missing costs."""
    names = ("gross_pnl_usd", "net_pnl_usd", "delay_usd", "spread_usd", "fees_usd", "funding_usd", "capacity_usd")
    raw = {name: value for name, value in locals().items() if name in names}
    values: dict[str, float] = {}
    missing: list[str] = []
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            missing.append(name)
        else:
            values[name] = float(value)
    if missing:
        return {"status": "UNMEASURABLE", "missing": missing, "paper_read_only": True, "real_execution": False}
    component_names = ("delay_usd", "spread_usd", "fees_usd", "funding_usd", "capacity_usd")
    components = {name: values[name] for name in component_names}
    costs = sum(components.values())
    residual = values["gross_pnl_usd"] - costs - values["net_pnl_usd"]
    return {
        "status": "PROVEN" if abs(residual) <= float(tolerance) else "REJECTED",
        "components": components,
        "reconciled_cost_usd": costs,
        "residual_usd": round(residual, 12),
        "dominant_component": max(components, key=components.get),
        "paper_read_only": True,
        "real_execution": False,
    }


def build_loss_attribution_report(log_dir: Path) -> LossAttributionReport:
    analysis = analyze_decision_logs(log_dir)
    costs = build_cost_breakdown(analysis)
    pnl = build_pnl_attribution(analysis)
    root_causes = classify_root_causes(analysis, costs)
    return LossAttributionReport(analysis=analysis, costs=costs, pnl=pnl, root_causes=root_causes)


def format_loss_attribution_report(report: LossAttributionReport) -> str:
    return "\n\n".join(
        [
            format_replay_analysis(report.analysis),
            format_cost_breakdown(report.costs),
            format_pnl_attribution(report.pnl),
            format_root_cause_report(report.root_causes),
            "security=simulation_only_no_real_order",
        ]
    )

