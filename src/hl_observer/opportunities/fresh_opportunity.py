from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScore,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.storage.models import PositionDeltaModel, TopWallet
from hl_observer.simulation.live_filters import copy_candidate_signal_time_ms
from hl_observer.wallets.delta_utils import copy_delta_action, copy_delta_direction


ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}


@dataclass(frozen=True, slots=True)
class FreshOpportunity:
    coin: str
    direction: str
    decision: str
    wallet_count: int
    wallets: tuple[str, ...]
    first_seen_ms: int
    last_seen_ms: int
    age_ms: int
    total_notional_usdc: float
    leader_reference_price: float
    current_mid: float | None
    current_mid_source: str
    average_leader_score: float
    expected_edge_bps: float | None
    edge_remaining_bps: float | None
    copy_degradation_bps: float
    opportunity_score: float
    risk_score: float
    simulated_notional_usdt: float
    refusal_reasons: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    research_only_message: str = (
        "Position virtuelle uniquement: aucune execution reelle, aucune garantie, score != signal."
    )


@dataclass(frozen=True, slots=True)
class FreshOpportunityReport:
    opportunities: tuple[FreshOpportunity, ...]
    deltas_seen: int
    entry_deltas_seen: int
    groups_seen: int
    accepted_for_simulation: int
    rejected: int
    rejection_reasons: tuple[tuple[str, int], ...]
    message: str = "research-only fresh opportunity scan; virtual positions only"


def find_fresh_opportunities(
    deltas: list[PositionDeltaModel],
    top_wallets: list[TopWallet],
    *,
    now_timestamp_ms: int,
    current_mids: dict[str, float] | None = None,
    active_window_ms: int = 20_000,
    consensus_window_ms: int = 4_000,
    min_wallets: int = 2,
    max_opportunities: int = 20,
    current_open_exposure_usdt: float = 0.0,
    current_open_positions: int = 0,
    max_open_positions: int = 6,
    risk_config: RealtimeCopyRiskConfig | None = None,
) -> FreshOpportunityReport:
    """Find same-coin/same-direction fresh clusters suitable for local simulation.

    This does not execute anything. It simply answers: "is there enough fresh
    multi-wallet evidence to *simulate* a virtual entry, after costs and gates?"
    """

    active_window_ms = max(1_000, int(active_window_ms))
    consensus_window_ms = max(1_000, min(active_window_ms, int(consensus_window_ms)))
    min_wallets = max(1, int(min_wallets))
    current_mids = {str(k).upper(): float(v) for k, v in (current_mids or {}).items() if _safe_float(v) is not None}
    score_by_wallet = {
        str(row.wallet_address or "").lower(): float(row.score or 0.0)
        for row in top_wallets
        if str(row.wallet_address or "").strip()
    }
    cutoff_ms = now_timestamp_ms - active_window_ms
    entry_rows: list[PositionDeltaModel] = []
    rejection_counts: dict[str, int] = {}

    for row in deltas:
        event_ms = copy_candidate_signal_time_ms(row)
        if event_ms <= 0:
            _count(rejection_counts, "MISSING_TIMESTAMP")
            continue
        if event_ms < cutoff_ms:
            _count(rejection_counts, "STALE_SIGNAL")
            continue
        action = copy_delta_action(row)
        direction = copy_delta_direction(row, action)
        if action not in ENTRY_ACTIONS or direction not in {"LONG", "SHORT"}:
            _count(rejection_counts, "NOT_FRESH_ENTRY")
            continue
        if _leader_price(row) <= 0:
            _count(rejection_counts, "PRICE_INVALID")
            continue
        entry_rows.append(row)

    opportunities: list[FreshOpportunity] = []
    for coin, direction in sorted({_coin_direction(row) for row in entry_rows}):
        rows = sorted(
            [
                row
                for row in entry_rows
                if str(row.coin or "").upper() == coin
                and copy_delta_direction(row, copy_delta_action(row)) == direction
            ],
            key=copy_candidate_signal_time_ms,
        )
        for index, seed in enumerate(rows):
            start_ms = copy_candidate_signal_time_ms(seed)
            cluster_rows = [row for row in rows[index:] if copy_candidate_signal_time_ms(row) <= start_ms + consensus_window_ms]
            wallets = tuple(sorted({str(row.wallet_address or "").lower() for row in cluster_rows if row.wallet_address}))
            if len(wallets) < min_wallets:
                _count(rejection_counts, "CLUSTER_BELOW_MIN_WALLETS")
                continue
            first_seen = min(copy_candidate_signal_time_ms(row) for row in cluster_rows)
            last_seen = max(copy_candidate_signal_time_ms(row) for row in cluster_rows)
            prices = [_leader_price(row) for row in cluster_rows if _leader_price(row) > 0]
            reference_price = float(median(prices)) if prices else 0.0
            mid = current_mids.get(coin)
            mid_source = "allMids" if mid is not None else "leader_reference_fallback"
            if mid is None:
                mid = reference_price
            leader_scores = [score_by_wallet.get(wallet, 50.0) for wallet in wallets]
            average_score = sum(leader_scores) / max(1, len(leader_scores))
            total_notional = sum(abs(float(row.delta_notional_usdc or 0.0)) for row in cluster_rows)
            expected_edge = _expected_edge_bps(
                average_leader_score=average_score,
                wallet_count=len(wallets),
                total_notional_usdc=total_notional,
                span_ms=max(0, last_seen - first_seen),
                consensus_window_ms=consensus_window_ms,
            )
            score = score_realtime_copy_candidate(
                RealtimeCopyScoreInput(
                    action_type="OPEN_LONG" if direction == "LONG" else "OPEN_SHORT",
                    direction=direction,
                    leader_expected_edge_bps=expected_edge,
                    leader_consistency_factor=_leader_consistency_factor(average_score),
                    signal_age_ms=max(0, now_timestamp_ms - last_seen),
                    consensus_wallets=len(wallets),
                    liquidity_score=_liquidity_score_from_notional(total_notional, len(wallets)),
                    leader_score=average_score,
                    leader_reference_price=reference_price,
                    current_mid=mid,
                    leader_notional_usdt=total_notional / max(1, len(wallets)),
                    current_open_exposure_usdt=current_open_exposure_usdt,
                    current_open_positions=current_open_positions,
                    max_open_positions=max_open_positions,
                ),
                config=risk_config,
            )
            warnings = list(score.warnings)
            if mid_source != "allMids":
                warnings.append("CURRENT_MID_FALLBACK_FROM_LEADER_PRICE")
            opportunities.append(
                FreshOpportunity(
                    coin=coin,
                    direction=direction,
                    decision=score.decision,
                    wallet_count=len(wallets),
                    wallets=wallets,
                    first_seen_ms=first_seen,
                    last_seen_ms=last_seen,
                    age_ms=max(0, now_timestamp_ms - last_seen),
                    total_notional_usdc=round(total_notional, 6),
                    leader_reference_price=round(reference_price, 8),
                    current_mid=round(mid, 8) if mid is not None else None,
                    current_mid_source=mid_source,
                    average_leader_score=round(average_score, 6),
                    expected_edge_bps=round(expected_edge, 6),
                    edge_remaining_bps=score.edge_remaining_bps,
                    copy_degradation_bps=score.copy_degradation_bps,
                    opportunity_score=score.opportunity_score,
                    risk_score=score.risk_score,
                    simulated_notional_usdt=score.simulated_notional_usdt,
                    refusal_reasons=tuple(score.refusal_reasons),
                    warnings=tuple(warnings),
                )
            )

    opportunities = _dedupe_and_rank(opportunities)[: max(1, int(max_opportunities))]
    for opportunity in opportunities:
        for reason in opportunity.refusal_reasons:
            _count(rejection_counts, reason)
    accepted = sum(1 for item in opportunities if item.decision == "ACCEPT_LOCAL_SIMULATION")
    rejected = sum(1 for item in opportunities if item.decision != "ACCEPT_LOCAL_SIMULATION")
    return FreshOpportunityReport(
        opportunities=tuple(opportunities),
        deltas_seen=len(deltas),
        entry_deltas_seen=len(entry_rows),
        groups_seen=len(opportunities),
        accepted_for_simulation=accepted,
        rejected=rejected,
        rejection_reasons=tuple(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)),
    )


def format_fresh_opportunity_report(report: FreshOpportunityReport) -> str:
    lines = [
        "opportunity_report=research_only",
        f"deltas_seen={report.deltas_seen}",
        f"entry_deltas_seen={report.entry_deltas_seen}",
        f"groups_seen={report.groups_seen}",
        f"accepted_for_virtual_simulation={report.accepted_for_simulation}",
        f"rejected={report.rejected}",
        "engine=edge_remaining_bps + freshness + liquidity + copy_degradation",
        "real_orders_created=0",
        "simulation_positions_are_virtual=true",
        "message=Fresh same-coin/same-direction clusters are ranked, then edge/cost/risk gates decide.",
    ]
    if report.opportunities:
        lines.append("opportunities:")
        for item in report.opportunities:
            reasons = ",".join(item.refusal_reasons) if item.refusal_reasons else "none"
            warnings = ",".join(item.warnings) if item.warnings else "none"
            lines.append(
                "- "
                f"{item.coin} {item.direction} decision={item.decision} "
                f"wallets={item.wallet_count} age_ms={item.age_ms} "
                f"edge={_fmt(item.edge_remaining_bps)}bps score={item.opportunity_score:.2f} "
                f"notional_virtual={item.simulated_notional_usdt:.2f} "
                f"degradation={item.copy_degradation_bps:.2f}bps reasons={reasons} warnings={warnings}"
            )
    else:
        lines.append("opportunities: none")
    if report.rejection_reasons:
        lines.append("rejection_reasons:")
        lines.extend(f"- {reason}: {count}" for reason, count in report.rejection_reasons[:20])
    return "\n".join(lines)


def _dedupe_and_rank(opportunities: list[FreshOpportunity]) -> list[FreshOpportunity]:
    ordered = sorted(
        opportunities,
        key=lambda item: (
            item.decision == "ACCEPT_LOCAL_SIMULATION",
            item.opportunity_score,
            item.wallet_count,
            -item.age_ms,
        ),
        reverse=True,
    )
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    kept: list[FreshOpportunity] = []
    for item in ordered:
        key = (item.coin, item.direction, item.wallets)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _expected_edge_bps(
    *,
    average_leader_score: float,
    wallet_count: int,
    total_notional_usdc: float,
    span_ms: int,
    consensus_window_ms: int,
) -> float:
    tightness = max(0.0, 1.0 - span_ms / max(1, consensus_window_ms))
    score_component = max(0.0, min(30.0, (average_leader_score - 50.0) * 0.55))
    consensus_component = min(28.0, max(0, wallet_count - 1) * 9.0)
    notional_component = min(16.0, total_notional_usdc / 25_000.0)
    tight_component = tightness * 10.0
    return round(14.0 + score_component + consensus_component + notional_component + tight_component, 6)


def _leader_consistency_factor(average_score: float) -> float:
    return round(max(0.55, min(1.18, average_score / 85.0)), 6)


def _liquidity_score_from_notional(total_notional_usdc: float, wallet_count: int) -> float:
    return round(max(0.2, min(1.0, 0.35 + wallet_count * 0.08 + total_notional_usdc / 250_000.0)), 6)


def _coin_direction(row: PositionDeltaModel) -> tuple[str, str]:
    return str(row.coin or "").upper(), str(copy_delta_direction(row, copy_delta_action(row)) or "UNKNOWN")


def _leader_price(row: PositionDeltaModel) -> float:
    return float(row.price or 0.0)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _count(target: dict[str, int], key: str) -> None:
    target[key] = target.get(key, 0) + 1


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"
