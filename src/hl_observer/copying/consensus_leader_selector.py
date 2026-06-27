from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.storage.models import PositionDeltaModel, TopWallet
from hl_observer.wallets.delta_utils import copy_delta_action, copy_delta_direction, delta_event_time_ms


ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}


@dataclass(frozen=True)
class ConsensusLeaderGroup:
    coin: str
    direction: str
    first_seen_ms: int
    last_seen_ms: int
    wallet_count: int
    wallets: list[str]
    total_notional_usdc: float
    average_leader_score: float
    consensus_score: float
    age_ms: int
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConsensusLeaderSelectionReport:
    groups_seen: int
    selected_wallets: list[str]
    groups: list[ConsensusLeaderGroup]
    rejected_reasons: dict[str, int]
    message: str = "research-only consensus selection; not a trading signal"


def select_consensus_leaders_from_deltas(
    deltas: list[PositionDeltaModel],
    top_wallets: list[TopWallet],
    *,
    now_timestamp_ms: int,
    max_leaders: int,
    active_window_ms: int = 5 * 60_000,
    consensus_window_ms: int = 4_000,
    min_wallets: int = 2,
    min_notional_usdc: float = 0.0,
) -> ConsensusLeaderSelectionReport:
    """Select wallets taking part in fresh same-coin/same-direction clusters.

    This is deliberately a selector, not an execution policy. It spends the
    bounded follow budget on leaders that recently agreed on a direction, while
    still allowing downstream edge, freshness and risk gates to refuse the
    simulated entry.
    """

    max_leaders = max(1, int(max_leaders))
    consensus_window_ms = max(1_000, int(consensus_window_ms))
    active_window_ms = max(consensus_window_ms, int(active_window_ms))
    min_wallets = max(2, int(min_wallets))
    score_by_wallet = {
        str(row.wallet_address or "").lower(): float(row.score or 0.0)
        for row in top_wallets
        if str(row.wallet_address or "").strip()
    }
    rejected: dict[str, int] = {}
    entries: list[PositionDeltaModel] = []
    cutoff = now_timestamp_ms - active_window_ms
    for row in deltas:
        event_ms = delta_event_time_ms(row)
        if event_ms <= 0:
            _count(rejected, "missing_timestamp")
            continue
        if event_ms < cutoff:
            _count(rejected, "stale_outside_active_window")
            continue
        action = copy_delta_action(row)
        direction = copy_delta_direction(row, action)
        if action not in ENTRY_ACTIONS or direction is None:
            _count(rejected, "not_entry_or_direction_unknown")
            continue
        entries.append(row)

    groups: list[ConsensusLeaderGroup] = []
    for coin, direction in sorted({_coin_direction(row) for row in entries}):
        rows = sorted(
            [
                row
                for row in entries
                if str(row.coin or "").upper() == coin
                and copy_delta_direction(row, copy_delta_action(row)) == direction
            ],
            key=delta_event_time_ms,
        )
        for index, seed in enumerate(rows):
            start_ms = delta_event_time_ms(seed)
            end_ms = start_ms + consensus_window_ms
            cluster_rows = [row for row in rows[index:] if delta_event_time_ms(row) <= end_ms]
            wallets = sorted({str(row.wallet_address or "").lower() for row in cluster_rows if row.wallet_address})
            if len(wallets) < min_wallets:
                _count(rejected, "cluster_below_min_wallets")
                continue
            total_notional = sum(abs(float(row.delta_notional_usdc or 0.0)) for row in cluster_rows)
            if total_notional < min_notional_usdc:
                _count(rejected, "cluster_below_min_notional")
                continue
            wallet_scores = [score_by_wallet.get(wallet, 50.0) for wallet in wallets]
            avg_score = sum(wallet_scores) / max(1, len(wallet_scores))
            first_seen = min(delta_event_time_ms(row) for row in cluster_rows)
            last_seen = max(delta_event_time_ms(row) for row in cluster_rows)
            span_ms = max(0, last_seen - first_seen)
            recency_score = max(0.0, 1.0 - (now_timestamp_ms - last_seen) / active_window_ms)
            tightness_score = max(0.0, 1.0 - span_ms / consensus_window_ms)
            notional_score = min(20.0, total_notional / 10_000.0)
            score = min(
                100.0,
                30.0
                + len(wallets) * 12.0
                + avg_score * 0.20
                + recency_score * 20.0
                + tightness_score * 12.0
                + notional_score,
            )
            warnings: list[str] = []
            if len(wallets) >= 5:
                warnings.append("crowding_risk_many_wallets_same_direction")
            if recency_score < 0.35:
                warnings.append("cluster_is_getting_stale")
            groups.append(
                ConsensusLeaderGroup(
                    coin=coin,
                    direction=direction,
                    first_seen_ms=first_seen,
                    last_seen_ms=last_seen,
                    wallet_count=len(wallets),
                    wallets=wallets,
                    total_notional_usdc=round(total_notional, 6),
                    average_leader_score=round(avg_score, 6),
                    consensus_score=round(score, 6),
                    age_ms=max(0, now_timestamp_ms - last_seen),
                    warnings=warnings,
                )
            )

    groups = _dedupe_groups(groups)
    selected: list[str] = []
    for group in groups:
        ranked_wallets = sorted(
            group.wallets,
            key=lambda wallet: (score_by_wallet.get(wallet, 50.0), wallet in score_by_wallet),
            reverse=True,
        )
        for wallet in ranked_wallets:
            if wallet not in selected:
                selected.append(wallet)
            if len(selected) >= max_leaders:
                break
        if len(selected) >= max_leaders:
            break

    return ConsensusLeaderSelectionReport(
        groups_seen=len(groups),
        selected_wallets=selected,
        groups=groups,
        rejected_reasons=rejected,
    )


def format_consensus_leader_report(report: ConsensusLeaderSelectionReport) -> str:
    lines = [
        "consensus_leader_report=research_only",
        f"groups_seen={report.groups_seen}",
        f"selected_wallets={len(report.selected_wallets)}",
        "message=Consensus boosts wallet selection only; downstream edge and risk gates still decide.",
    ]
    if report.selected_wallets:
        lines.append("selected:")
        lines.extend(f"- {wallet}" for wallet in report.selected_wallets)
    if report.groups:
        lines.append("groups:")
        for group in report.groups[:20]:
            warnings = ",".join(group.warnings) if group.warnings else "none"
            lines.append(
                "- "
                f"{group.coin} {group.direction} wallets={group.wallet_count} "
                f"score={group.consensus_score:.2f} age_ms={group.age_ms} "
                f"notional={group.total_notional_usdc:.2f} warnings={warnings}"
            )
    if report.rejected_reasons:
        lines.append("rejected_reasons:")
        for reason, count in sorted(report.rejected_reasons.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- {reason}: {count}")
    lines.append("orders_created=0")
    lines.append("simulation_only=true")
    return "\n".join(lines)


def _coin_direction(row: PositionDeltaModel) -> tuple[str, str]:
    return str(row.coin or "").upper(), str(copy_delta_direction(row, copy_delta_action(row)) or "UNKNOWN")


def _dedupe_groups(groups: list[ConsensusLeaderGroup]) -> list[ConsensusLeaderGroup]:
    ordered = sorted(
        groups,
        key=lambda item: (item.consensus_score, item.wallet_count, item.last_seen_ms),
        reverse=True,
    )
    kept: list[ConsensusLeaderGroup] = []
    seen_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    for group in ordered:
        key = (group.coin, group.direction, tuple(group.wallets))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        kept.append(group)
    return kept


def _count(target: dict[str, int], key: str) -> None:
    target[key] = target.get(key, 0) + 1
