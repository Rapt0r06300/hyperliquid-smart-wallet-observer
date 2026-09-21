"""Executable markout evaluation for Event Intelligence research candidates.

This module is retrospective replay measurement only. It never sends an order.
Entry and exit use Hyperliquid BBO sides, while the economic decomposition keeps
spread separate from fees, slippage and latency so the canonical scoreboard can
remain honest about every cost component.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.collection.native_venue_market import (
    NativeMarketSnapshot,
    canonical_coin,
)
from hl_observer.event_intelligence.candidates import EventLeadLagCandidate


SCHEMA_VERSION = "alina.event_candidate_markout.v1"


@dataclass(frozen=True, slots=True)
class EventCandidateMarkout:
    event_id: str
    event_kind: str
    coin: str
    direction: str | None
    decision_ts_ms: int
    horizon_ms: int
    status: str
    reason: str
    entry_ts_ms: int | None = None
    exit_ts_ms: int | None = None
    entry_mid: float | None = None
    exit_mid: float | None = None
    entry_executable_px: float | None = None
    exit_executable_px: float | None = None
    gross_mid_bps: float | None = None
    executable_markout_bps: float | None = None
    spread_bps: float | None = None
    fees_bps: float | None = None
    slippage_bps: float | None = None
    latency_bps: float | None = None
    total_cost_bps: float | None = None
    net_bps: float | None = None
    notional_usd: float | None = None
    net_pnl_usd: float | None = None
    capacity_usd: float | None = None
    fill_ratio: float | None = None
    entry_latency_ms: int | None = None
    real_execution: bool = False

    @property
    def measured(self) -> bool:
        return self.status == "MEASURED" and self.net_bps is not None


def evaluate_candidate_markout(
    candidate: EventLeadLagCandidate,
    snapshots: Iterable[NativeMarketSnapshot],
    *,
    horizon_ms: int,
    entry_latency_ms: int = 0,
    max_entry_wait_ms: int = 1_000,
    max_exit_wait_ms: int = 1_000,
    fees_bps: float | None,
    slippage_bps: float | None,
    latency_bps: float | None,
    notional_usd: float = 50.0,
    hyperliquid_venue: str = "hyperliquid",
) -> EventCandidateMarkout:
    """Measure one candidate using the first eligible BBO after entry/exit targets."""

    horizon = int(horizon_ms)
    entry_delay = int(entry_latency_ms)
    if horizon <= 0:
        raise ValueError("horizon_ms must be > 0")
    if entry_delay < 0:
        raise ValueError("entry_latency_ms must be >= 0")
    if int(max_entry_wait_ms) < 0 or int(max_exit_wait_ms) < 0:
        raise ValueError("wait limits must be >= 0")
    notional = float(notional_usd)
    if notional <= 0.0:
        raise ValueError("notional_usd must be > 0")

    base = dict(
        event_id=candidate.event_id,
        event_kind=candidate.event_kind,
        coin=canonical_coin(candidate.coin),
        direction=candidate.research_direction,
        decision_ts_ms=int(candidate.decision_ts_ms),
        horizon_ms=horizon,
        notional_usd=notional,
        real_execution=False,
    )
    if not candidate.is_candidate:
        return EventCandidateMarkout(
            **base,
            status="UNMEASURABLE",
            reason="INPUT_NOT_CANDIDATE",
        )
    if candidate.research_direction not in {"UPWARD_HL_LAG", "DOWNWARD_HL_LAG"}:
        return EventCandidateMarkout(
            **base,
            status="UNMEASURABLE",
            reason="DIRECTION_MISSING",
        )

    venue = str(hyperliquid_venue).strip().lower()
    target_coin = canonical_coin(candidate.coin)
    rows = sorted(
        (
            snap
            for snap in snapshots
            if snap.exploitable
            and snap.venue == venue
            and canonical_coin(snap.coin) == target_coin
            and snap.receive_ts_ms >= candidate.decision_ts_ms
        ),
        key=lambda snap: snap.receive_ts_ms,
    )
    entry_target = candidate.decision_ts_ms + entry_delay
    entry = _first_at_or_after(
        rows,
        target_ms=entry_target,
        max_wait_ms=int(max_entry_wait_ms),
    )
    if entry is None:
        return EventCandidateMarkout(
            **base,
            status="UNMEASURABLE",
            reason="ENTRY_BBO_MISSING",
        )

    exit_target = entry.receive_ts_ms + horizon
    exit_snap = _first_at_or_after(
        rows,
        target_ms=exit_target,
        max_wait_ms=int(max_exit_wait_ms),
    )
    if exit_snap is None:
        return EventCandidateMarkout(
            **base,
            status="UNMEASURABLE",
            reason="EXIT_BBO_MISSING",
            entry_ts_ms=entry.receive_ts_ms,
            entry_latency_ms=entry.receive_ts_ms - candidate.decision_ts_ms,
        )

    is_up = candidate.research_direction == "UPWARD_HL_LAG"
    direction_sign = 1.0 if is_up else -1.0
    if is_up:
        entry_px = entry.ask
        exit_px = exit_snap.bid
        entry_spread = (entry.ask - entry.mid) / entry.mid * 10_000.0
        exit_spread = (exit_snap.mid - exit_snap.bid) / exit_snap.mid * 10_000.0
    else:
        entry_px = entry.bid
        exit_px = exit_snap.ask
        entry_spread = (entry.mid - entry.bid) / entry.mid * 10_000.0
        exit_spread = (exit_snap.ask - exit_snap.mid) / exit_snap.mid * 10_000.0

    gross_mid = direction_sign * (exit_snap.mid / entry.mid - 1.0) * 10_000.0
    executable = direction_sign * (exit_px / entry_px - 1.0) * 10_000.0
    spread = entry_spread + exit_spread
    capacity = _roundtrip_top_capacity_usd(entry, exit_snap, is_up=is_up)
    fill_ratio = (
        min(1.0, capacity / notional)
        if capacity is not None and notional > 0.0
        else None
    )

    values = (fees_bps, slippage_bps, latency_bps)
    if any(value is None for value in values):
        return EventCandidateMarkout(
            **base,
            status="UNMEASURABLE",
            reason="COST_COMPONENT_MISSING",
            entry_ts_ms=entry.receive_ts_ms,
            exit_ts_ms=exit_snap.receive_ts_ms,
            entry_mid=entry.mid,
            exit_mid=exit_snap.mid,
            entry_executable_px=entry_px,
            exit_executable_px=exit_px,
            gross_mid_bps=gross_mid,
            executable_markout_bps=executable,
            spread_bps=spread,
            fees_bps=None if fees_bps is None else float(fees_bps),
            slippage_bps=None if slippage_bps is None else float(slippage_bps),
            latency_bps=None if latency_bps is None else float(latency_bps),
            capacity_usd=capacity,
            fill_ratio=fill_ratio,
            entry_latency_ms=entry.receive_ts_ms - candidate.decision_ts_ms,
        )

    fees = float(fees_bps)
    slippage = float(slippage_bps)
    latency_cost = float(latency_bps)
    if min(fees, slippage, latency_cost) < 0.0:
        raise ValueError("cost components must be >= 0")
    total_cost = spread + fees + slippage + latency_cost
    net = gross_mid - total_cost
    pnl = notional * net / 10_000.0

    return EventCandidateMarkout(
        **base,
        status="MEASURED",
        reason="EXECUTABLE_MARKOUT_MEASURED",
        entry_ts_ms=entry.receive_ts_ms,
        exit_ts_ms=exit_snap.receive_ts_ms,
        entry_mid=entry.mid,
        exit_mid=exit_snap.mid,
        entry_executable_px=entry_px,
        exit_executable_px=exit_px,
        gross_mid_bps=gross_mid,
        executable_markout_bps=executable,
        spread_bps=spread,
        fees_bps=fees,
        slippage_bps=slippage,
        latency_bps=latency_cost,
        total_cost_bps=total_cost,
        net_bps=net,
        net_pnl_usd=pnl,
        capacity_usd=capacity,
        fill_ratio=fill_ratio,
        entry_latency_ms=entry.receive_ts_ms - candidate.decision_ts_ms,
    )


def _first_at_or_after(
    rows: Iterable[NativeMarketSnapshot],
    *,
    target_ms: int,
    max_wait_ms: int,
) -> NativeMarketSnapshot | None:
    for snap in rows:
        if snap.receive_ts_ms < int(target_ms):
            continue
        if snap.receive_ts_ms - int(target_ms) > int(max_wait_ms):
            return None
        return snap
    return None


def _roundtrip_top_capacity_usd(
    entry: NativeMarketSnapshot,
    exit_snap: NativeMarketSnapshot,
    *,
    is_up: bool,
) -> float | None:
    if is_up:
        entry_levels = entry.asks
        exit_levels = exit_snap.bids
    else:
        entry_levels = entry.bids
        exit_levels = exit_snap.asks
    if not entry_levels or not exit_levels:
        return None
    entry_capacity = float(entry_levels[0].price) * float(entry_levels[0].size)
    exit_capacity = float(exit_levels[0].price) * float(exit_levels[0].size)
    if entry_capacity <= 0.0 or exit_capacity <= 0.0:
        return None
    return min(entry_capacity, exit_capacity)


__all__ = [
    "EventCandidateMarkout",
    "SCHEMA_VERSION",
    "evaluate_candidate_markout",
]
