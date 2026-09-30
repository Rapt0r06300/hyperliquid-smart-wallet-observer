from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from hl_observer.simulation.decision_replay_analyzer import DecisionEvent, ReplayAnalysis, analyze_decision_logs


@dataclass(frozen=True, slots=True)
class SimulationTuningReport:
    source_dir: Path
    event_count: int
    accepted_count: int
    refused_count: int
    current_policy: str
    stale_ratio: float
    positive_events: int
    negative_events: int
    total_pnl_usdc: float
    fees_usdc: float
    recommended_max_signal_age_ms: int
    recommended_min_consensus_wallets: int
    recommended_max_parallel_positions: int
    recommended_blocked_coins: tuple[str, ...]
    recommended_watch_coins: tuple[str, ...]
    recommended_blocked_wallets: tuple[str, ...]
    top_reasons: tuple[tuple[str, int], ...]
    notes_fr: tuple[str, ...]


def build_simulation_tuning_report(log_dir: Path) -> SimulationTuningReport:
    analysis = analyze_decision_logs(log_dir)
    stale_ratio = _stale_ratio(analysis.events)
    losing_coins = _negative_rank(analysis.pnl_by_coin, limit=8, threshold=-0.05)
    winning_coins = _positive_rank(analysis.pnl_by_coin, limit=8, threshold=0.02)
    losing_wallets = _negative_rank(analysis.pnl_by_wallet, limit=12, threshold=-0.10)
    notes = _notes_fr(analysis, stale_ratio, losing_coins, winning_coins)
    return SimulationTuningReport(
        source_dir=log_dir,
        event_count=analysis.event_count,
        accepted_count=analysis.accepted_count,
        refused_count=analysis.refused_count,
        current_policy="simulation_only_no_order_no_mainnet",
        stale_ratio=round(stale_ratio, 6),
        positive_events=analysis.positive_count,
        negative_events=analysis.negative_count,
        total_pnl_usdc=analysis.total_estimated_pnl_usdc,
        fees_usdc=analysis.total_fees_usdc,
        recommended_max_signal_age_ms=3_000,
        recommended_min_consensus_wallets=3 if stale_ratio > 0.50 or analysis.total_estimated_pnl_usdc < 0 else 2,
        recommended_max_parallel_positions=6 if analysis.total_estimated_pnl_usdc < 0 else 10,
        recommended_blocked_coins=tuple(coin for coin, _pnl in losing_coins),
        recommended_watch_coins=tuple(coin for coin, _pnl in winning_coins),
        recommended_blocked_wallets=tuple(wallet for wallet, _pnl in losing_wallets),
        top_reasons=analysis.top_refusal_reasons[:10],
        notes_fr=notes,
    )


def format_simulation_tuning_report(report: SimulationTuningReport) -> str:
    lines = [
        "simulation_tuning_report=research_only",
        f"source_dir={report.source_dir}",
        f"events={report.event_count}",
        f"accepted={report.accepted_count}",
        f"refused={report.refused_count}",
        f"total_pnl_usdc={report.total_pnl_usdc:.6f}",
        f"fees_usdc={report.fees_usdc:.6f}",
        f"stale_ratio={report.stale_ratio:.6f}",
        f"recommended_max_signal_age_ms={report.recommended_max_signal_age_ms}",
        f"recommended_min_consensus_wallets={report.recommended_min_consensus_wallets}",
        f"recommended_max_parallel_positions={report.recommended_max_parallel_positions}",
        "recommended_blocked_coins=" + ",".join(report.recommended_blocked_coins),
        "recommended_watch_coins=" + ",".join(report.recommended_watch_coins),
        "recommended_blocked_wallets=" + ",".join(report.recommended_blocked_wallets),
        "notes_fr:",
    ]
    lines.extend(f"- {note}" for note in report.notes_fr)
    if report.top_reasons:
        lines.append("top_no_trade_reasons:")
        lines.extend(f"- {reason}: {count}" for reason, count in report.top_reasons)
    lines.append("execution=forbidden")
    lines.append("paper_simulation_only=true")
    lines.append("profit_guarantee=false")
    return "\n".join(lines)


def _stale_ratio(events: tuple[DecisionEvent, ...]) -> float:
    measured = [event for event in events if event.signal_age_ms is not None]
    if not measured:
        return 0.0
    stale = sum(1 for event in measured if int(event.signal_age_ms or 0) > 3_000)
    return stale / len(measured)


def _negative_rank(values: dict[str, float], *, limit: int, threshold: float) -> list[tuple[str, float]]:
    rows = [(key, pnl) for key, pnl in values.items() if pnl <= threshold]
    return sorted(rows, key=lambda item: item[1])[:limit]


def _positive_rank(values: dict[str, float], *, limit: int, threshold: float) -> list[tuple[str, float]]:
    rows = [(key, pnl) for key, pnl in values.items() if pnl >= threshold]
    return sorted(rows, key=lambda item: item[1], reverse=True)[:limit]


def _notes_fr(
    analysis: ReplayAnalysis,
    stale_ratio: float,
    losing_coins: list[tuple[str, float]],
    winning_coins: list[tuple[str, float]],
) -> tuple[str, ...]:
    notes: list[str] = []
    if stale_ratio > 0.50:
        notes.append(
            "La priorite n'est pas de scanner brutalement plus fort: il faut recevoir les ouvertures fraiches via WS/read-only shortlist, sinon la copie arrive trop tard."
        )
    if analysis.total_estimated_pnl_usdc < 0:
        notes.append(
            "Le PnL log-event est negatif: bloquer temporairement les coins/wallets perdants et exiger 3 wallets alignes avant nouvelle entree."
        )
    if analysis.total_fees_usdc > abs(analysis.total_estimated_pnl_usdc):
        notes.append(
            "Les frais et couts dominent le resultat: reduire les petites entrees et refuser les edges restants faibles."
        )
    if losing_coins:
        notes.append("Coins a mettre en pause locale: " + ", ".join(coin for coin, _ in losing_coins[:5]) + ".")
    if winning_coins:
        notes.append("Coins a garder en observation prioritaire: " + ", ".join(coin for coin, _ in winning_coins[:5]) + ".")
    if not notes:
        notes.append("Aucun recalibrage urgent detecte; continuer a accumuler des logs frais.")
    notes.append("Aucune ligne de ce rapport ne cree un ordre: simulation locale uniquement.")
    return tuple(notes)
