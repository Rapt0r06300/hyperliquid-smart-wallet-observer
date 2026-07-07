"""Distilled GitHub-inspired opportunity detector.

This is the first replacement for the old "external GitHub bus writes trades"
approach. External repositories inspire the policy, but the runtime uses one
local, measurable detector:

fresh leader candidates -> same coin/side consensus -> ranked opportunity.

It is read-only and paper-only. It never writes a position and never bypasses
RiskEngine/PaperEngine.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from hl_observer.signals.opportunity_ranker import OpportunityInput, RankerConfig, rank_opportunities

ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}


@dataclass(frozen=True, slots=True)
class DistilledOpportunityConfig:
    max_signal_age_ms: int = 4_000
    min_wallets: int = 2
    min_total_notional_usdc: float = 5_000.0
    min_edge_remaining_bps: float = 8.0
    min_liquidity_score: float = 0.30
    max_copy_degradation_bps: float = 35.0
    max_opportunities: int = 5
    max_per_coin: int = 2


@dataclass(frozen=True, slots=True)
class DistilledSignalCandidate:
    coin: str
    side: str
    leader_wallet: str
    action_type: str
    event_time_ms: int
    leader_notional_usdc: float
    edge_remaining_bps: float | None
    liquidity_score: float = 0.5
    leader_score: float = 50.0
    copy_degradation_bps: float = 0.0
    source_profile: str = "canonical"


@dataclass(frozen=True, slots=True)
class DistilledOpportunity:
    coin: str
    side: str
    wallet_count: int
    wallets: tuple[str, ...]
    total_notional_usdc: float
    average_edge_bps: float
    average_liquidity_score: float
    max_signal_age_ms: int
    power_score: float
    source_profiles: tuple[str, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)
    paper_only: bool = True
    read_only: bool = True
    real_execution: bool = False


@dataclass(frozen=True, slots=True)
class DistilledOpportunityReport:
    evaluated_candidates: int
    opportunities: tuple[DistilledOpportunity, ...]
    rejected_reasons: dict[str, int]
    message: str = "distilled GitHub ideas; research-only paper opportunity ranking"


def detect_distilled_opportunities(
    candidates: list[DistilledSignalCandidate],
    *,
    now_ms: int,
    config: DistilledOpportunityConfig | None = None,
) -> DistilledOpportunityReport:
    cfg = config or DistilledOpportunityConfig()
    rejected: dict[str, int] = {}
    buckets: dict[tuple[str, str], list[tuple[DistilledSignalCandidate, int]]] = defaultdict(list)

    for candidate in candidates:
        coin = str(candidate.coin or "").upper().strip()
        side = str(candidate.side or "").upper().strip()
        action = str(candidate.action_type or "").upper().strip()
        if coin == "" or side not in {"LONG", "SHORT"}:
            _count(rejected, "invalid_coin_or_side")
            continue
        if action not in ENTRY_ACTIONS:
            _count(rejected, "not_entry_action")
            continue
        age_ms = max(0, int(now_ms) - int(candidate.event_time_ms or 0))
        if age_ms > int(cfg.max_signal_age_ms):
            _count(rejected, "stale_signal")
            continue
        edge = candidate.edge_remaining_bps
        if edge is None:
            _count(rejected, "edge_missing")
            continue
        if float(edge) < float(cfg.min_edge_remaining_bps):
            _count(rejected, "edge_too_low")
            continue
        if float(candidate.liquidity_score or 0.0) < float(cfg.min_liquidity_score):
            _count(rejected, "liquidity_too_low")
            continue
        if float(candidate.copy_degradation_bps or 0.0) > float(cfg.max_copy_degradation_bps):
            _count(rejected, "copy_degradation_too_high")
            continue
        buckets[(coin, side)].append((candidate, age_ms))

    opportunities: list[DistilledOpportunity] = []
    for (coin, side), rows in buckets.items():
        wallets = tuple(sorted({str(row.leader_wallet or "").lower() for row, _ in rows if row.leader_wallet}))
        if len(wallets) < int(cfg.min_wallets):
            _count(rejected, "cluster_below_min_wallets")
            continue
        total_notional = sum(max(0.0, float(row.leader_notional_usdc or 0.0)) for row, _ in rows)
        if total_notional < float(cfg.min_total_notional_usdc):
            _count(rejected, "cluster_below_min_notional")
            continue
        average_edge = sum(float(row.edge_remaining_bps or 0.0) for row, _ in rows) / max(1, len(rows))
        average_liquidity = sum(float(row.liquidity_score or 0.0) for row, _ in rows) / max(1, len(rows))
        max_age = max(age for _, age in rows)
        leader_scores = [float(row.leader_score or 50.0) for row, _ in rows]
        leader_winrate_proxy = max(0.0, min(1.0, (sum(leader_scores) / max(1, len(leader_scores))) / 100.0))
        ranked = rank_opportunities(
            [
                OpportunityInput(
                    coin=coin,
                    side=side,
                    net_edge_bps=average_edge,
                    signal_age_ms=max_age,
                    consensus_wallets=len(wallets),
                    liquidity_score=average_liquidity,
                    leader_winrate=leader_winrate_proxy,
                )
            ],
            RankerConfig(
                min_net_edge_bps=cfg.min_edge_remaining_bps,
                min_liquidity_score=cfg.min_liquidity_score,
                max_signal_age_ms=cfg.max_signal_age_ms,
                max_per_coin=cfg.max_per_coin,
            ),
            limit=1,
        )
        if not ranked:
            _count(rejected, "ranker_floor_rejected")
            continue
        profiles = tuple(sorted({str(row.source_profile or "canonical") for row, _ in rows}))
        reasons = ["FRESH_CONSENSUS", "EDGE_AFTER_COST", "LIQUIDITY_OK"]
        if len(wallets) >= 3:
            reasons.append("THREE_PLUS_WALLETS")
        opportunities.append(
            DistilledOpportunity(
                coin=coin,
                side=side,
                wallet_count=len(wallets),
                wallets=wallets,
                total_notional_usdc=round(total_notional, 6),
                average_edge_bps=round(average_edge, 6),
                average_liquidity_score=round(average_liquidity, 6),
                max_signal_age_ms=max_age,
                power_score=ranked[0].power_score,
                source_profiles=profiles,
                reasons=tuple(reasons),
            )
        )

    opportunities.sort(key=lambda item: (item.power_score, item.wallet_count, item.total_notional_usdc), reverse=True)
    limited = tuple(opportunities[: max(1, int(cfg.max_opportunities))])
    return DistilledOpportunityReport(
        evaluated_candidates=len(candidates),
        opportunities=limited,
        rejected_reasons=rejected,
    )


def _count(target: dict[str, int], reason: str) -> None:
    target[reason] = target.get(reason, 0) + 1


__all__ = [
    "DistilledOpportunity",
    "DistilledOpportunityConfig",
    "DistilledOpportunityReport",
    "DistilledSignalCandidate",
    "detect_distilled_opportunities",
]
