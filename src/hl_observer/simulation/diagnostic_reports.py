from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from hl_observer.simulation.log_metrics import LogMetricsReport, analyze_logs_streaming, build_recommendations


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    name: str
    lines: tuple[str, ...]


def build_root_cause_from_logs(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    causes: list[str] = []
    if metrics.net_pnl_usdc < 0:
        causes.append("PNL_NET_NEGATIF_APRES_COUTS")
    if metrics.reasons["STALE_SIGNAL"]:
        causes.append("SIGNAUX_TROP_VIEUX")
    if metrics.edge_sentinel_count or metrics.edge_negative_count:
        causes.append("EDGE_NON_MESURABLE_OU_NEGATIF")
    if metrics.reasons["NO_MATCHING_PAPER_POSITION_FOR_CLOSE"]:
        causes.append("FERMETURES_SANS_POSITION_PAPER")
    if metrics.reasons["COPY_DEGRADATION_TOO_HIGH"]:
        causes.append("DEGRADATION_COPIE_TROP_FORTE")
    if metrics.reasons["PRICE_DEVIATION_TOO_HIGH"]:
        causes.append("PRIX_TROP_ELOIGNE_DU_LEADER")
    if metrics.fee_drag_ratio > 0.25:
        causes.append("FRAIS_TROP_IMPORTANTS_VS_EDGE")
    if not causes:
        causes.append("PAS_DE_CAUSE_DOMINANTE_DANS_LES_LOGS")
    lines = [
        "root_cause_from_logs=simulation_read_only",
        f"source_dir={log_dir}",
        f"net_pnl_usdc={metrics.net_pnl_usdc:.6f}",
        f"fees_usdc={metrics.fees_usdc:.6f}",
        f"fee_drag_ratio={metrics.fee_drag_ratio:.6f}",
        "causes:",
        *(f"- {cause}" for cause in causes),
        "actions_correctives:",
        *(f"- {item}" for item in build_recommendations(metrics)),
        "execution=forbidden",
    ]
    return DiagnosticReport("root_cause_from_logs", tuple(lines))


def build_profitability_diagnostics(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    lines = [
        "profitability_diagnostics=net_after_costs",
        f"source_dir={log_dir}",
        f"gross_pnl_usdc={metrics.gross_pnl_usdc:.6f}",
        f"net_pnl_usdc={metrics.net_pnl_usdc:.6f}",
        f"fees_usdc={metrics.fees_usdc:.6f}",
        f"fee_drag_ratio={metrics.fee_drag_ratio:.6f}",
        f"net_winrate={metrics.net_winrate:.6f}",
        f"profit_factor_net={metrics.profit_factor_net:.6f}",
        f"positive_events={metrics.positive_events}",
        f"negative_events={metrics.negative_events}",
        "interpretation_fr=" + _profitability_interpretation(metrics),
    ]
    return DiagnosticReport("profitability_diagnostics", tuple(lines))


def build_refusal_breakdown(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    lines = [
        "refusal_breakdown=simulation_read_only",
        f"refused={metrics.refused}",
        f"accepted={metrics.accepted}",
        "top_refusal_reasons:",
        *(f"- {reason}: {count}" for reason, count in metrics.reasons.most_common(25)),
    ]
    return DiagnosticReport("refusal_breakdown", tuple(lines))


def build_cost_drag_diagnostics(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    lines = [
        "cost_drag_diagnostics=simulation_read_only",
        f"gross_pnl_usdc={metrics.gross_pnl_usdc:.6f}",
        f"fees_usdc={metrics.fees_usdc:.6f}",
        f"fee_drag_ratio={metrics.fee_drag_ratio:.6f}",
        "fees_by_action:",
        *_rank_lines(metrics.fees_by_action, reverse=True, limit=20),
        "recommendation=augmenter_min_edge_et_min_notional_si_fee_drag_ratio_est_eleve",
    ]
    return DiagnosticReport("cost_drag_diagnostics", tuple(lines))


def build_position_matching_diagnostics(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    close_orphan = metrics.reasons["NO_MATCHING_PAPER_POSITION_FOR_CLOSE"]
    ratio = close_orphan / metrics.total_decisions if metrics.total_decisions else 0.0
    lines = [
        "position_matching_diagnostics=simulation_read_only",
        f"orphan_close_count={close_orphan}",
        f"orphan_close_ratio={ratio:.8f}",
        f"add_without_original_open_count={metrics.reasons['ADD_WITHOUT_ORIGINAL_OPEN_REFUSED']}",
        "policy=REDUCE/CLOSE_sans_position_paper_observe_only_pas_de_pnl",
    ]
    return DiagnosticReport("position_matching_diagnostics", tuple(lines))


def build_stale_signal_diagnostics(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    age_values = sorted(metrics.signal_age_values)
    stale_3s = sum(1 for age in age_values if age > 3_000)
    stale_20s = sum(1 for age in age_values if age > 20_000)
    measured = len(age_values)
    lines = [
        "stale_signal_diagnostics=simulation_read_only",
        f"measured_signal_ages={measured}",
        f"stale_over_3000_ms={stale_3s}",
        f"stale_over_3000_ratio={stale_3s / measured if measured else 0:.8f}",
        f"stale_over_20000_ms={stale_20s}",
        f"stale_over_20000_ratio={stale_20s / measured if measured else 0:.8f}",
        f"stale_signal_reason_count={metrics.reasons['STALE_SIGNAL']}",
        "recommendation=max_signal_age_ms_strict_et_ws_shortlist_read_only",
    ]
    return DiagnosticReport("stale_signal_diagnostics", tuple(lines))


def build_wallet_loss_diagnostics(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    return DiagnosticReport(
        "wallet_loss_diagnostics",
        tuple(["wallet_loss_diagnostics=simulation_read_only", "top_losing_wallets:", *_rank_lines(metrics.pnl_by_wallet, reverse=False, limit=25)]),
    )


def build_coin_loss_diagnostics(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    return DiagnosticReport(
        "coin_loss_diagnostics",
        tuple(["coin_loss_diagnostics=simulation_read_only", "top_losing_coins:", *_rank_lines(metrics.pnl_by_coin, reverse=False, limit=25)]),
    )


def build_action_loss_diagnostics(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    return DiagnosticReport(
        "action_loss_diagnostics",
        tuple(["action_loss_diagnostics=simulation_read_only", "pnl_by_action:", *_rank_lines(metrics.pnl_by_action, reverse=False, limit=25)]),
    )


def build_edge_distribution_diagnostics(log_dir: Path) -> DiagnosticReport:
    metrics = analyze_logs_streaming(log_dir)
    buckets = Counter[str]()
    for edge in metrics.edge_values:
        if edge <= -9_000:
            buckets["sentinel_-9999"] += 1
        elif edge < 0:
            buckets["negative"] += 1
        elif edge < 25:
            buckets["0_to_25"] += 1
        elif edge < 60:
            buckets["25_to_60"] += 1
        else:
            buckets["60_plus"] += 1
    lines = [
        "edge_distribution_diagnostics=simulation_read_only",
        f"edge_sentinel_count={metrics.edge_sentinel_count}",
        f"edge_negative_count={metrics.edge_negative_count}",
        f"edge_positive_count={metrics.edge_positive_count}",
        "buckets:",
        *(f"- {name}: {count}" for name, count in buckets.most_common()),
    ]
    return DiagnosticReport("edge_distribution_diagnostics", tuple(lines))


def build_timing_distribution_diagnostics(log_dir: Path) -> DiagnosticReport:
    return build_stale_signal_diagnostics(log_dir)


def format_diagnostic_report(report: DiagnosticReport) -> str:
    return "\n".join(report.lines)


def _rank_lines(values: dict[str, float], *, reverse: bool, limit: int) -> list[str]:
    return [f"- {key}: {value:.6f}" for key, value in sorted(values.items(), key=lambda item: item[1], reverse=reverse)[:limit]]


def _profitability_interpretation(metrics: LogMetricsReport) -> str:
    if metrics.net_pnl_usdc > 0:
        return "PnL net positif dans ces logs, mais validation hors-echantillon obligatoire avant promotion."
    if metrics.gross_pnl_usdc >= 0 and metrics.net_pnl_usdc < 0:
        return "PnL brut non negatif mais PnL net negatif: les couts detruisent l'opportunite."
    return "PnL net negatif: filtrage edge/fraicheur/wallets/coins a renforcer avant toute entree paper."
