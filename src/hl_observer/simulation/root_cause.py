from __future__ import annotations

from dataclasses import dataclass

from hl_observer.simulation.cost_breakdown import CostBreakdown
from hl_observer.simulation.decision_replay_analyzer import ReplayAnalysis


@dataclass(frozen=True, slots=True)
class RootCauseReport:
    causes: tuple[str, ...]
    plain_french: tuple[str, ...]


def classify_root_causes(analysis: ReplayAnalysis, costs: CostBreakdown) -> RootCauseReport:
    causes: list[str] = []
    fr: list[str] = []
    if analysis.event_count == 0:
        causes.append("NO_DECISIONS_RECORDED")
        fr.append("Aucune decision n'a ete enregistree: il faut verifier le scanner et le flux UI.")
    if analysis.refused_count and analysis.accepted_count == 0:
        causes.append("ALL_SIGNALS_REFUSED")
        fr.append("Tous les signaux ont ete refuses: regarder les raisons no-trade avant de changer le risque.")
    if analysis.negative_count > analysis.positive_count and analysis.negative_count > 0:
        causes.append("NEGATIVE_EVENTS_DOMINATE")
        fr.append("Les evenements perdants sont plus nombreux que les gagnants dans les logs recents.")
    if costs.total_fees_usdc > 0 and analysis.total_estimated_pnl_usdc <= costs.total_fees_usdc:
        causes.append("FEES_DRAG")
        fr.append("Les frais pesent fortement par rapport au PnL simule.")
    if costs.max_copy_degradation_bps is not None and costs.max_copy_degradation_bps >= 30:
        causes.append("COPY_DEGRADATION_TOO_HIGH")
        fr.append("Le signal semble trop degrade par retard, spread, slippage ou liquidite.")
    if any(event.signal_age_ms is not None and event.signal_age_ms > 20_000 for event in analysis.events):
        causes.append("LATE_ENTRY")
        fr.append("Au moins une entree arrive apres la fenetre fraiche configuree de simulation.")
    if any((event.edge_remaining_bps or 0) > 20 and (event.estimated_net_pnl_usdc or 0) < 0 for event in analysis.events):
        causes.append("EDGE_MODEL_TOO_OPTIMISTIC")
        fr.append("Un edge positif estime a fini negatif: le modele doit etre recalibre avec les couts reels.")
    if not causes:
        causes.append("NO_MAJOR_LOSS_CAUSE_DETECTED")
        fr.append("Aucune cause dominante detectee; continuer a accumuler des logs avant d'ajuster.")
    return RootCauseReport(causes=tuple(dict.fromkeys(causes)), plain_french=tuple(dict.fromkeys(fr)))


def format_root_cause_report(report: RootCauseReport) -> str:
    lines = ["root_cause_report=simulation_only", "causes:"]
    lines.extend(f"- {cause}" for cause in report.causes)
    lines.append("explications_fr:")
    lines.extend(f"- {item}" for item in report.plain_french)
    return "\n".join(lines)
