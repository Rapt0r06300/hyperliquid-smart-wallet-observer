from __future__ import annotations

from dataclasses import dataclass
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

