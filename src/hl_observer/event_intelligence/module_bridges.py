"""Pure bridges from Event Intelligence into Alina's three research modules.

These bridges add context and measurable features. They never bypass the native
economic gates of Lead-Lag, Cross-Venue or Copy-Vault.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable

from hl_observer.event_intelligence.candidates import EventLeadLagCandidate
from hl_observer.event_intelligence.regimes import (
    AssetRelevance,
    EventRegime,
    classify_event_regime,
    map_event_to_assets,
)
from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent


@dataclass(frozen=True, slots=True)
class LeadLagEventContext:
    event_id: str
    regime: EventRegime
    assets: tuple[str, ...]
    candidate_status: str
    leader_venue: str | None
    net_room_bps: float | None
    replay_eligible: bool
    reason: str
    may_bypass_native_economics: bool = False


@dataclass(frozen=True, slots=True)
class CrossVenueEventContext:
    event_id: str
    regime: EventRegime
    event_age_ms: int
    in_event_window: bool
    assets: tuple[str, ...]
    filter_only: bool = True
    may_bypass_costs: bool = False
    may_bypass_capacity: bool = False


@dataclass(frozen=True, slots=True)
class LeaderAction:
    leader_id: str
    ts_ms: int
    asset: str
    side: str


@dataclass(frozen=True, slots=True)
class CopyVaultLeaderEventStats:
    leader_id: str
    event_family: str
    observations: int
    median_reaction_ms: float | None
    p90_reaction_ms: float | None
    fast_reaction_ratio: float | None
    reacted_before_market_ratio: float | None


def build_lead_lag_event_context(
    event: WorldMonitorEvent,
    candidate: EventLeadLagCandidate,
    *,
    available_assets: Iterable[str] = (),
) -> LeadLagEventContext:
    relevance = map_event_to_assets(event, available_assets=available_assets)
    regime = classify_event_regime(
        event,
        market_moved=candidate.leader_venue is not None,
        event_available_before_move=candidate.event_age_ms >= 0,
    )
    eligible = (
        candidate.status == "CANDIDATE"
        and candidate.net_room_bps is not None
        and candidate.net_room_bps > 0.0
        and event.usable_for_signal
    )
    reason = (
        "EVENT_CONFIRMED_NET_LAG"
        if eligible
        else f"EVENT_CONTEXT_ONLY:{candidate.reason}"
    )
    return LeadLagEventContext(
        event_id=event.event.event_id,
        regime=regime.regime,
        assets=relevance.assets,
        candidate_status=candidate.status,
        leader_venue=candidate.leader_venue,
        net_room_bps=candidate.net_room_bps,
        replay_eligible=eligible,
        reason=reason,
    )


def build_cross_venue_event_context(
    event: WorldMonitorEvent,
    *,
    decision_ts_ms: int,
    available_assets: Iterable[str] = (),
    event_window_ms: int = 300_000,
) -> CrossVenueEventContext:
    age = int(decision_ts_ms) - int(event.event.available_ts_ms)
    in_window = (
        0 <= age <= max(0, int(event_window_ms))
        and event.usable_for_signal
    )
    relevance = map_event_to_assets(event, available_assets=available_assets)
    regime = classify_event_regime(
        event,
        market_moved=False,
        event_available_before_move=True,
    )
    return CrossVenueEventContext(
        event_id=event.event.event_id,
        regime=regime.regime,
        event_age_ms=age,
        in_event_window=in_window,
        assets=relevance.assets,
    )


def measure_copy_vault_event_reactions(
    events: Iterable[WorldMonitorEvent],
    actions: Iterable[LeaderAction],
    *,
    event_family: str,
    market_first_reaction_ms: dict[str, int] | None = None,
    max_reaction_ms: int = 300_000,
    fast_threshold_ms: int = 30_000,
) -> dict[str, CopyVaultLeaderEventStats]:
    """Measure leader reaction latency after causally available external events."""

    family = str(event_family)
    usable_events = [
        row for row in events
        if row.usable_for_signal and _family(row) == family
    ]
    action_rows = sorted(
        actions,
        key=lambda row: (row.leader_id, int(row.ts_ms), row.asset),
    )
    per_leader: dict[str, list[tuple[int, bool]]] = {}
    for event in usable_events:
        relevant = map_event_to_assets(
            event,
            available_assets={action.asset.upper() for action in action_rows},
        )
        if not relevant.assets:
            continue
        for leader in sorted({action.leader_id for action in action_rows}):
            candidates = [
                action
                for action in action_rows
                if action.leader_id == leader
                and action.asset.upper() in set(relevant.assets)
                and int(action.ts_ms) >= event.event.available_ts_ms
                and int(action.ts_ms) - event.event.available_ts_ms
                <= int(max_reaction_ms)
            ]
            if not candidates:
                continue
            first = min(candidates, key=lambda action: int(action.ts_ms))
            latency = int(first.ts_ms) - event.event.available_ts_ms
            market_ts = (
                (market_first_reaction_ms or {}).get(event.event.event_id)
            )
            before_market = market_ts is not None and int(first.ts_ms) < int(market_ts)
            per_leader.setdefault(leader, []).append((latency, before_market))

    output: dict[str, CopyVaultLeaderEventStats] = {}
    for leader, rows in sorted(per_leader.items()):
        latencies = sorted(float(latency) for latency, _ in rows)
        fast = sum(latency <= float(fast_threshold_ms) for latency in latencies)
        before = sum(bool(flag) for _, flag in rows)
        output[leader] = CopyVaultLeaderEventStats(
            leader_id=leader,
            event_family=family,
            observations=len(rows),
            median_reaction_ms=(
                round(statistics.median(latencies), 6) if latencies else None
            ),
            p90_reaction_ms=_percentile(latencies, 0.90),
            fast_reaction_ratio=(
                round(fast / len(rows), 6) if rows else None
            ),
            reacted_before_market_ratio=(
                round(before / len(rows), 6) if rows else None
            ),
        )
    return output


def _family(event: WorldMonitorEvent) -> str:
    kind = str(event.kind or "").strip()
    if kind:
        return kind
    return event.event.event_type.value.casefold()


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 6)
    pos = (len(ordered) - 1) * float(q)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return round(ordered[lo], 6)
    weight = pos - lo
    return round(ordered[lo] * (1.0 - weight) + ordered[hi] * weight, 6)


__all__ = [
    "CopyVaultLeaderEventStats",
    "CrossVenueEventContext",
    "LeadLagEventContext",
    "LeaderAction",
    "build_cross_venue_event_context",
    "build_lead_lag_event_context",
    "measure_copy_vault_event_reactions",
]
