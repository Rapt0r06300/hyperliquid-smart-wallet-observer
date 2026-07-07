from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from hl_observer.simulation.decision_replay_analyzer import default_logs_to_send_dir
from hl_observer.simulation.log_metrics import LogMetricsReport, analyze_logs_streaming


@dataclass(frozen=True, slots=True)
class CalibrationFlagCandidate:
    name: str
    proposed_value: str
    reason: str
    replay_test: str
    activation_rule: str = "activate_only_if_replay_ab_improves_net_profit_factor_without_lookahead"


@dataclass(frozen=True, slots=True)
class LedgerPnlCalibrationReport:
    source_dir: Path
    source_files: tuple[str, ...]
    total_decisions: int
    accepted: int
    refused: int
    net_pnl_usdc: float
    fees_usdc: float
    fee_drag_ratio: float
    net_winrate: float
    profit_factor_net: float
    max_consecutive_losses: int
    negative_events: int
    positive_events: int
    open_positions_count: int
    open_exposure_usdt: float
    unrealized_pnl_usdc: float
    top_losing_coins: tuple[tuple[str, float], ...]
    top_winning_coins: tuple[tuple[str, float], ...]
    top_refusal_reasons: tuple[tuple[str, int], ...]
    flag_candidates: tuple[CalibrationFlagCandidate, ...]
    diagnosis_fr: tuple[str, ...]


def build_ledger_pnl_calibration_report(log_dir: Path | None = None) -> LedgerPnlCalibrationReport:
    effective_dir = log_dir or default_logs_to_send_dir()
    metrics = analyze_logs_streaming(effective_dir)
    runtime = _snapshot_runtime_metrics(effective_dir)
    losing_coins = _rank_negative(metrics.pnl_by_coin, limit=8)
    winning_coins = _rank_positive(metrics.pnl_by_coin, limit=8)
    flags = _flag_candidates(metrics, losing_coins, runtime)
    return LedgerPnlCalibrationReport(
        source_dir=effective_dir,
        source_files=tuple(path.name for path in metrics.source_files),
        total_decisions=metrics.total_decisions,
        accepted=metrics.accepted,
        refused=metrics.refused,
        net_pnl_usdc=round(metrics.net_pnl_usdc, 8),
        fees_usdc=round(metrics.fees_usdc, 8),
        fee_drag_ratio=metrics.fee_drag_ratio,
        net_winrate=metrics.net_winrate,
        profit_factor_net=metrics.profit_factor_net,
        max_consecutive_losses=metrics.max_consecutive_losses,
        negative_events=metrics.negative_events,
        positive_events=metrics.positive_events,
        open_positions_count=runtime["open_positions_count"],
        open_exposure_usdt=round(runtime["open_exposure_usdt"], 8),
        unrealized_pnl_usdc=round(runtime["unrealized_pnl_usdc"], 8),
        top_losing_coins=tuple(losing_coins),
        top_winning_coins=tuple(winning_coins),
        top_refusal_reasons=tuple(metrics.reasons.most_common(12)),
        flag_candidates=tuple(flags),
        diagnosis_fr=tuple(_diagnosis_fr(metrics, losing_coins, winning_coins, runtime)),
    )


def format_ledger_pnl_calibration_report(report: LedgerPnlCalibrationReport) -> str:
    lines = [
        "ledger_pnl_calibration=research_only",
        f"source_dir={report.source_dir}",
        "source_files=" + ",".join(report.source_files),
        f"total_decisions={report.total_decisions}",
        f"accepted={report.accepted}",
        f"refused={report.refused}",
        f"net_pnl_usdc={report.net_pnl_usdc:.6f}",
        f"fees_usdc={report.fees_usdc:.6f}",
        f"fee_drag_ratio={report.fee_drag_ratio:.6f}",
        f"net_winrate={report.net_winrate:.6f}",
        f"profit_factor_net={report.profit_factor_net:.6f}",
        f"max_consecutive_losses={report.max_consecutive_losses}",
        f"open_positions_count={report.open_positions_count}",
        f"open_exposure_usdt={report.open_exposure_usdt:.6f}",
        f"unrealized_pnl_usdc={report.unrealized_pnl_usdc:.6f}",
        "diagnosis_fr:",
    ]
    lines.extend(f"- {item}" for item in report.diagnosis_fr)
    lines.append("flag_candidates:")
    if report.flag_candidates:
        for item in report.flag_candidates:
            lines.append(
                f"- {item.name}={item.proposed_value} :: reason={item.reason} :: "
                f"replay={item.replay_test} :: activation={item.activation_rule}"
            )
    else:
        lines.append("- none :: continuer la collecte ledger avant recalibrage")
    if report.top_losing_coins:
        lines.append("top_losing_coins:")
        lines.extend(f"- {coin}: {pnl:.6f}" for coin, pnl in report.top_losing_coins)
    if report.top_winning_coins:
        lines.append("top_winning_coins:")
        lines.extend(f"- {coin}: {pnl:.6f}" for coin, pnl in report.top_winning_coins)
    if report.top_refusal_reasons:
        lines.append("top_refusal_reasons:")
        lines.extend(f"- {reason}: {count}" for reason, count in report.top_refusal_reasons)
    lines.extend(
        [
            "apply_automatically=false",
            "replay_ab_required=true",
            "execution=forbidden",
            "paper_simulation_only=true",
            "profit_guarantee=false",
        ]
    )
    return "\n".join(lines)


def _flag_candidates(
    metrics: LogMetricsReport,
    losing_coins: list[tuple[str, float]],
    runtime: dict[str, float | int],
) -> list[CalibrationFlagCandidate]:
    candidates: list[CalibrationFlagCandidate] = []
    if metrics.net_pnl_usdc < 0 or metrics.profit_factor_net < 1.0:
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_REQUIRE_PROFIT_FACTOR_REPLAY_GATE",
                proposed_value="true",
                reason=f"profit_factor_net={metrics.profit_factor_net:.4f} net_pnl={metrics.net_pnl_usdc:.4f}",
                replay_test="baseline_vs_profit_factor_gate",
            )
        )
    if metrics.fee_drag_ratio > 0.35:
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_MIN_PAPER_NOTIONAL_USDT",
                proposed_value="40",
                reason=f"fee_drag_ratio={metrics.fee_drag_ratio:.4f} > 0.35",
                replay_test="baseline_vs_no_micro_trades_40usdt",
            )
        )
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_MIN_EDGE_AFTER_COST_BPS",
                proposed_value="45",
                reason="les frais/couts mangent l'edge observe",
                replay_test="baseline_vs_edge45_after_cost",
            )
        )
    if metrics.net_winrate and metrics.net_winrate < 0.45:
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_MIN_CONSENSUS_WALLETS",
                proposed_value="3",
                reason=f"winrate={metrics.net_winrate:.4f} < 0.45",
                replay_test="baseline_vs_consensus3",
            )
        )
    if metrics.max_consecutive_losses >= 3:
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_LOSS_STREAK_COOLDOWN",
                proposed_value="3",
                reason=f"max_consecutive_losses={metrics.max_consecutive_losses}",
                replay_test="baseline_vs_loss_streak_cooldown",
            )
        )
    if int(runtime.get("open_positions_count") or 0) > 8:
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_MAX_OPEN_PAPER_POSITIONS",
                proposed_value="5",
                reason=f"open_positions_count={int(runtime.get('open_positions_count') or 0)} expose trop la session",
                replay_test="baseline_vs_max_open_positions_5",
            )
        )
    if float(runtime.get("unrealized_pnl_usdc") or 0.0) < -1.0:
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_UNREALIZED_DRAWDOWN_GUARD_USDT",
                proposed_value="1.0",
                reason=f"unrealized_pnl={float(runtime.get('unrealized_pnl_usdc') or 0.0):.4f} pese sur le PnL live",
                replay_test="baseline_vs_unrealized_drawdown_guard",
            )
        )
    stale_count = (
        metrics.reasons["STALE_SIGNAL"]
        + metrics.reasons["REJECT_TOO_LATE"]
        + metrics.reasons["opportunity stale signal"]
        + metrics.reasons["entry deltas too old for copy"]
    )
    if stale_count > max(3, metrics.total_decisions * 0.05):
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_MAX_SIGNAL_AGE_MS",
                proposed_value="4000",
                reason=f"stale_or_late_refusals={stale_count}",
                replay_test="baseline_vs_fresh_4s",
            )
        )
    if losing_coins:
        candidates.append(
            CalibrationFlagCandidate(
                name="HYPERSMART_REPLAY_COIN_COOLDOWN_SET",
                proposed_value=",".join(coin for coin, _ in losing_coins[:5]),
                reason="coins les plus defavorables dans le ledger courant",
                replay_test="baseline_vs_losing_coin_cooldown",
            )
        )
    return candidates


def _snapshot_runtime_metrics(log_dir: Path) -> dict[str, float | int]:
    path = log_dir / "simulation_snapshot_latest.json"
    if not path.exists() or path.stat().st_size <= 0:
        return {"open_positions_count": 0, "open_exposure_usdt": 0.0, "unrealized_pnl_usdc": 0.0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"open_positions_count": 0, "open_exposure_usdt": 0.0, "unrealized_pnl_usdc": 0.0}
    bot = payload.get("bot_simulation") if isinstance(payload, dict) else {}
    paper_ledger = payload.get("paper_ledger") if isinstance(payload, dict) else {}
    if not isinstance(bot, dict):
        bot = {}
    if not isinstance(paper_ledger, dict):
        paper_ledger = {}
    open_positions = bot.get("open_positions")
    open_positions_count = len(open_positions) if isinstance(open_positions, list) else int(_safe_float(paper_ledger.get("open_positions_count")) or 0)
    return {
        "open_positions_count": open_positions_count,
        "open_exposure_usdt": _safe_float(bot.get("open_exposure_usdt")) or 0.0,
        "unrealized_pnl_usdc": _safe_float(bot.get("unrealized_pnl_usdc") or paper_ledger.get("unrealized_pnl_usdc")) or 0.0,
    }


def _diagnosis_fr(
    metrics: LogMetricsReport,
    losing_coins: list[tuple[str, float]],
    winning_coins: list[tuple[str, float]],
    runtime: dict[str, float | int],
) -> list[str]:
    notes: list[str] = []
    if metrics.total_decisions <= 0:
        notes.append("Aucun evenement ferme exploitable dans le ledger: verifier que le serveur a exporte les logs frais.")
    if metrics.total_decisions > 0:
        if metrics.net_pnl_usdc < 0:
            notes.append(
                "Le ledger canonique est negatif: il faut durcir les entrees et tester les sorties en replay, pas augmenter le risque."
            )
        else:
            notes.append("Le ledger canonique est positif sur cet extrait, mais il doit etre confirme par replay A/B et run plus long.")
    if metrics.fee_drag_ratio > 0.35:
        notes.append("Les frais/couts sont trop lourds par rapport au brut: eviter les micro-trades et exiger plus d'edge.")
    if metrics.profit_factor_net < 1.0:
        notes.append("Le profit factor net est sous 1: les pertes nettes dominent les gains nets.")
    if metrics.net_winrate and metrics.net_winrate < 0.45:
        notes.append("Le taux de trades gagnants est faible: exiger plus de consensus et de fraicheur avant entree.")
    if int(runtime.get("open_positions_count") or 0) > 8:
        notes.append(
            "La session garde trop de positions ouvertes: plafonner les positions simultanees avant de chercher plus d'entrees."
        )
    if float(runtime.get("unrealized_pnl_usdc") or 0.0) < -1.0:
        notes.append("Le latent ouvert est negatif: verifier SL/TP, time-stop et drawdown guard sur positions ouvertes.")
    if losing_coins:
        notes.append("Coins a tester en cooldown local: " + ", ".join(coin for coin, _ in losing_coins[:5]) + ".")
    if winning_coins:
        notes.append("Coins a garder en observation prioritaire: " + ", ".join(coin for coin, _ in winning_coins[:5]) + ".")
    notes.append("Aucun flag propose ici ne doit etre active sans replay A/B net de frais et sans lookahead.")
    return notes


def _safe_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rank_negative(values: dict[str, float], *, limit: int) -> list[tuple[str, float]]:
    rows = [(key, round(value, 8)) for key, value in values.items() if key and value < 0]
    return sorted(rows, key=lambda item: item[1])[:limit]


def _rank_positive(values: dict[str, float], *, limit: int) -> list[tuple[str, float]]:
    rows = [(key, round(value, 8)) for key, value in values.items() if key and value > 0]
    return sorted(rows, key=lambda item: item[1], reverse=True)[:limit]


__all__ = [
    "CalibrationFlagCandidate",
    "LedgerPnlCalibrationReport",
    "build_ledger_pnl_calibration_report",
    "format_ledger_pnl_calibration_report",
]
