"""Measure causal information-to-market price discovery across native venues.

The output is research evidence only. It does not declare an event causal, does not
estimate executable PnL, and never submits orders. All timing uses Alina receive
timestamps so replay cannot use information before it was actually ingested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.collection.native_venue_market import (
    NativeMarketSnapshot,
    canonical_coin,
)
from hl_observer.event_intelligence.external_event import ExternalEvent


SCHEMA_VERSION = "alina.event_market_reaction.v1"


@dataclass(frozen=True, slots=True)
class EventMarketReaction:
    event_id: str
    coin: str
    status: str
    available_ts_ms: int
    horizon_ms: int
    threshold_bps: float
    baseline_venues: tuple[str, ...]
    reacted_venues: tuple[str, ...]
    first_venue: str | None = None
    first_reaction_ts_ms: int | None = None
    first_reaction_latency_ms: int | None = None
    hyperliquid_reaction_ts_ms: int | None = None
    hyperliquid_reaction_latency_ms: int | None = None
    leader_to_hyperliquid_lag_ms: int | None = None
    first_move_bps: float | None = None
    hyperliquid_move_bps: float | None = None
    initial_leader_hl_gap_bps: float | None = None
    reaction_gap_half_life_ms: int | None = None
    peak_dispersion_bps: float = 0.0
    real_execution: bool = False

    @property
    def external_event_led_market(self) -> bool:
        return (
            self.first_reaction_ts_ms is not None
            and self.first_reaction_ts_ms >= self.available_ts_ms
        )


def measure_event_price_discovery(
    event: ExternalEvent,
    snapshots: Iterable[NativeMarketSnapshot],
    *,
    coin: str,
    threshold_bps: float = 5.0,
    horizon_ms: int = 60_000,
    hyperliquid_venue: str = "hyperliquid",
) -> EventMarketReaction:
    """Measure which venue first crosses a post-event move threshold.

    A venue baseline is its latest exploitable snapshot at or before the event's
    causal availability timestamp. Post-event moves are measured only from receive
    timestamps at or after that timestamp.
    """

    target = canonical_coin(coin)
    hl_venue = str(hyperliquid_venue).strip().lower()
    threshold = float(threshold_bps)
    horizon = int(horizon_ms)
    if not target:
        raise ValueError("coin is required")
    if threshold <= 0.0:
        raise ValueError("threshold_bps must be > 0")
    if horizon <= 0:
        raise ValueError("horizon_ms must be > 0")

    rows = sorted(
        (
            snap
            for snap in snapshots
            if snap.exploitable and canonical_coin(snap.coin) == target
        ),
        key=lambda snap: (snap.receive_ts_ms, snap.venue),
    )
    baselines: dict[str, NativeMarketSnapshot] = {}
    for snap in rows:
        if snap.receive_ts_ms <= event.available_ts_ms:
            previous = baselines.get(snap.venue)
            if previous is None or snap.receive_ts_ms >= previous.receive_ts_ms:
                baselines[snap.venue] = snap

    baseline_venues = tuple(sorted(baselines))
    if not baselines:
        return EventMarketReaction(
            event_id=event.event_id,
            coin=target,
            status="NO_BASELINE",
            available_ts_ms=event.available_ts_ms,
            horizon_ms=horizon,
            threshold_bps=threshold,
            baseline_venues=(),
            reacted_venues=(),
        )

    end_ts_ms = event.available_ts_ms + horizon
    latest_moves = {venue: 0.0 for venue in baselines}
    reaction_times: dict[str, int] = {}
    reaction_moves: dict[str, float] = {}
    first_venue: str | None = None
    first_ts: int | None = None
    first_move: float | None = None
    initial_gap: float | None = None
    gap_half_life: int | None = None
    peak_dispersion = 0.0

    for snap in rows:
        if snap.receive_ts_ms < event.available_ts_ms:
            continue
        if snap.receive_ts_ms > end_ts_ms:
            break
        baseline = baselines.get(snap.venue)
        if baseline is None or baseline.mid <= 0.0:
            continue

        move_bps = (snap.mid / baseline.mid - 1.0) * 10_000.0
        latest_moves[snap.venue] = move_bps
        if len(latest_moves) >= 2:
            dispersion = max(latest_moves.values()) - min(latest_moves.values())
            peak_dispersion = max(peak_dispersion, abs(dispersion))

        if snap.venue not in reaction_times and abs(move_bps) >= threshold:
            reaction_times[snap.venue] = snap.receive_ts_ms
            reaction_moves[snap.venue] = move_bps
            if first_ts is None:
                first_venue = snap.venue
                first_ts = snap.receive_ts_ms
                first_move = move_bps
                hl_move = latest_moves.get(hl_venue, 0.0)
                initial_gap = abs(move_bps - hl_move)
                if first_venue == hl_venue:
                    gap_half_life = 0

        if (
            first_ts is not None
            and first_venue is not None
            and first_venue != hl_venue
            and initial_gap is not None
            and initial_gap > 0.0
            and gap_half_life is None
            and first_venue in latest_moves
            and hl_venue in latest_moves
        ):
            current_gap = abs(
                latest_moves[first_venue] - latest_moves[hl_venue]
            )
            if current_gap <= initial_gap / 2.0:
                gap_half_life = snap.receive_ts_ms - first_ts

    reacted_venues = tuple(
        venue
        for venue, _ts in sorted(
            reaction_times.items(),
            key=lambda item: (item[1], item[0]),
        )
    )
    if first_ts is None or first_venue is None:
        status = "NO_REACTION"
    elif first_venue == hl_venue:
        status = "HYPERLIQUID_FIRST"
    elif hl_venue in reaction_times:
        status = "LEADER_THEN_HYPERLIQUID"
    else:
        status = "LEADER_ONLY_WITHIN_HORIZON"

    hl_ts = reaction_times.get(hl_venue)
    hl_move = reaction_moves.get(hl_venue)
    return EventMarketReaction(
        event_id=event.event_id,
        coin=target,
        status=status,
        available_ts_ms=event.available_ts_ms,
        horizon_ms=horizon,
        threshold_bps=threshold,
        baseline_venues=baseline_venues,
        reacted_venues=reacted_venues,
        first_venue=first_venue,
        first_reaction_ts_ms=first_ts,
        first_reaction_latency_ms=(
            first_ts - event.available_ts_ms if first_ts is not None else None
        ),
        hyperliquid_reaction_ts_ms=hl_ts,
        hyperliquid_reaction_latency_ms=(
            hl_ts - event.available_ts_ms if hl_ts is not None else None
        ),
        leader_to_hyperliquid_lag_ms=(
            hl_ts - first_ts
            if hl_ts is not None and first_ts is not None
            else None
        ),
        first_move_bps=first_move,
        hyperliquid_move_bps=hl_move,
        initial_leader_hl_gap_bps=initial_gap,
        reaction_gap_half_life_ms=gap_half_life,
        peak_dispersion_bps=peak_dispersion,
        real_execution=False,
    )


__all__ = [
    "EventMarketReaction",
    "SCHEMA_VERSION",
    "measure_event_price_discovery",
]
