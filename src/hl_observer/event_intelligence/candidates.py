"""Causal Event Intelligence candidate generation.

A candidate is research evidence, not an order instruction. The engine only uses
information and market snapshots available at decision_ts_ms and explicitly
accounts for the Hyperliquid executable side. If economic costs are unknown, the
candidate is UNMEASURABLE rather than silently promoted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.collection.native_venue_market import (
    NativeMarketSnapshot,
    canonical_coin,
)
from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent


SCHEMA_VERSION = "alina.event_lead_lag_candidate.v1"


@dataclass(frozen=True, slots=True)
class EventLeadLagConfig:
    min_leader_move_bps: float = 4.0
    min_gross_room_bps: float = 2.0
    min_net_room_bps: float = 1.0
    max_event_age_ms: int = 120_000
    max_current_snapshot_age_ms: int = 1_000
    max_baseline_age_ms: int = 5_000
    min_news_importance: float = 50.0
    min_news_credibility: float = 40.0
    min_prediction_delta_pp: float = 5.0
    min_cross_source_severity: float = 0.50
    min_event_confidence: float = 0.50
    min_corroboration_count: int = 1
    min_confirming_venues: int = 1

    def __post_init__(self) -> None:
        if self.min_leader_move_bps <= 0:
            raise ValueError("min_leader_move_bps must be > 0")
        if self.min_gross_room_bps < 0 or self.min_net_room_bps < 0:
            raise ValueError("room thresholds must be >= 0")
        if min(
            self.max_event_age_ms,
            self.max_current_snapshot_age_ms,
            self.max_baseline_age_ms,
        ) <= 0:
            raise ValueError("age limits must be > 0")
        if self.min_prediction_delta_pp <= 0:
            raise ValueError("min_prediction_delta_pp must be > 0")
        if not 0.0 <= float(self.min_event_confidence) <= 1.0:
            raise ValueError("min_event_confidence must be in [0, 1]")
        if self.min_corroboration_count < 1 or self.min_confirming_venues < 1:
            raise ValueError("minimum counts must be >= 1")


@dataclass(frozen=True, slots=True)
class EventLeadLagCandidate:
    event_id: str
    event_kind: str
    coin: str
    decision_ts_ms: int
    status: str
    reason: str
    event_age_ms: int
    leader_venue: str | None = None
    confirming_venues: tuple[str, ...] = ()
    research_direction: str | None = None
    leader_move_bps: float | None = None
    hyperliquid_mid_move_bps: float | None = None
    hyperliquid_executable_move_bps: float | None = None
    gross_room_bps: float | None = None
    cost_floor_bps: float | None = None
    net_room_bps: float | None = None
    leader_snapshot_age_ms: int | None = None
    hyperliquid_snapshot_age_ms: int | None = None
    event_importance_score: float | None = None
    event_credibility_score: float | None = None
    event_corroboration_count: int = 1
    prediction_delta_pp: float | None = None
    real_execution: bool = False

    @property
    def is_candidate(self) -> bool:
        return self.status == "CANDIDATE"

    @property
    def economically_measurable(self) -> bool:
        return self.cost_floor_bps is not None and self.net_room_bps is not None


def evaluate_event_lead_lag_candidate(
    world_event: WorldMonitorEvent,
    snapshots: Iterable[NativeMarketSnapshot],
    *,
    coin: str,
    decision_ts_ms: int,
    cost_floor_bps: float | None,
    config: EventLeadLagConfig = EventLeadLagConfig(),
    hyperliquid_venue: str = "hyperliquid",
) -> EventLeadLagCandidate:
    """Evaluate an information -> venue leader -> Hyperliquid lag at one instant.

    No snapshot after decision_ts_ms is considered. A pre-event baseline is also
    required to be recent relative to the event ingest time.
    """

    decision = int(decision_ts_ms)
    event = world_event.event
    target = canonical_coin(coin)
    hl_venue = str(hyperliquid_venue).strip().lower()
    if not target:
        raise ValueError("coin is required")
    if decision < event.available_ts_ms:
        return _result(
            world_event,
            target,
            decision,
            "REJECTED",
            "FUTURE_INFORMATION",
            event_age_ms=decision - event.available_ts_ms,
        )
    event_age = decision - event.available_ts_ms
    if event_age > int(config.max_event_age_ms):
        return _result(
            world_event,
            target,
            decision,
            "REJECTED",
            "EVENT_TOO_OLD",
            event_age_ms=event_age,
        )
    if not world_event.usable_for_signal:
        return _result(
            world_event,
            target,
            decision,
            "REJECTED",
            "SOURCE_NOT_USABLE",
            event_age_ms=event_age,
        )

    quality_reason = _event_quality_reason(world_event, config)
    if quality_reason is not None:
        return _result(
            world_event,
            target,
            decision,
            "REJECTED",
            quality_reason,
            event_age_ms=event_age,
        )

    rows = sorted(
        (
            snap
            for snap in snapshots
            if snap.exploitable
            and canonical_coin(snap.coin) == target
            and snap.receive_ts_ms <= decision
        ),
        key=lambda snap: (snap.receive_ts_ms, snap.venue),
    )
    baselines: dict[str, NativeMarketSnapshot] = {}
    current: dict[str, NativeMarketSnapshot] = {}
    for snap in rows:
        if snap.receive_ts_ms <= event.available_ts_ms:
            age_at_event = event.available_ts_ms - snap.receive_ts_ms
            if age_at_event <= int(config.max_baseline_age_ms):
                previous = baselines.get(snap.venue)
                if previous is None or snap.receive_ts_ms >= previous.receive_ts_ms:
                    baselines[snap.venue] = snap
        if snap.receive_ts_ms >= event.available_ts_ms:
            age_now = decision - snap.receive_ts_ms
            if age_now <= int(config.max_current_snapshot_age_ms):
                previous = current.get(snap.venue)
                if previous is None or snap.receive_ts_ms >= previous.receive_ts_ms:
                    current[snap.venue] = snap

    hl_base = baselines.get(hl_venue)
    hl_now = current.get(hl_venue)
    if hl_base is None or hl_now is None:
        return _result(
            world_event,
            target,
            decision,
            "UNMEASURABLE",
            "HYPERLIQUID_BASELINE_OR_CURRENT_MISSING",
            event_age_ms=event_age,
        )

    moves: dict[str, float] = {}
    for venue, snap in current.items():
        baseline = baselines.get(venue)
        if baseline is None or baseline.mid <= 0.0:
            continue
        moves[venue] = (snap.mid / baseline.mid - 1.0) * 10_000.0

    non_hl_moves = {
        venue: move for venue, move in moves.items() if venue != hl_venue
    }
    if not non_hl_moves:
        return _result(
            world_event,
            target,
            decision,
            "WATCH",
            "NO_NON_HL_MARKET_CONFIRMATION",
            event_age_ms=event_age,
        )

    leader_venue, leader_move = max(
        non_hl_moves.items(),
        key=lambda item: (abs(item[1]), item[0]),
    )
    if abs(leader_move) < float(config.min_leader_move_bps):
        return _result(
            world_event,
            target,
            decision,
            "WATCH",
            "LEADER_MOVE_BELOW_THRESHOLD",
            event_age_ms=event_age,
            leader_venue=leader_venue,
            leader_move_bps=leader_move,
        )

    direction_sign = 1.0 if leader_move > 0 else -1.0
    confirming = tuple(
        sorted(
            venue
            for venue, move in non_hl_moves.items()
            if abs(move) >= float(config.min_leader_move_bps)
            and (1.0 if move > 0 else -1.0) == direction_sign
        )
    )
    if len(confirming) < int(config.min_confirming_venues):
        return _result(
            world_event,
            target,
            decision,
            "WATCH",
            "INSUFFICIENT_CONFIRMING_VENUES",
            event_age_ms=event_age,
            leader_venue=leader_venue,
            confirming_venues=confirming,
            leader_move_bps=leader_move,
        )

    hl_mid_move = (hl_now.mid / hl_base.mid - 1.0) * 10_000.0
    if direction_sign > 0:
        executable_price = hl_now.ask
        research_direction = "UPWARD_HL_LAG"
    else:
        executable_price = hl_now.bid
        research_direction = "DOWNWARD_HL_LAG"
    hl_executable_move = (executable_price / hl_base.mid - 1.0) * 10_000.0
    gross_room = direction_sign * (leader_move - hl_executable_move)

    common = dict(
        event_age_ms=event_age,
        leader_venue=leader_venue,
        confirming_venues=confirming,
        research_direction=research_direction,
        leader_move_bps=leader_move,
        hyperliquid_mid_move_bps=hl_mid_move,
        hyperliquid_executable_move_bps=hl_executable_move,
        gross_room_bps=gross_room,
        leader_snapshot_age_ms=decision - current[leader_venue].receive_ts_ms,
        hyperliquid_snapshot_age_ms=decision - hl_now.receive_ts_ms,
    )
    if gross_room < float(config.min_gross_room_bps):
        return _result(
            world_event,
            target,
            decision,
            "REJECTED",
            "NO_EXECUTABLE_HYPERLIQUID_LAG",
            **common,
        )

    if cost_floor_bps is None:
        return _result(
            world_event,
            target,
            decision,
            "UNMEASURABLE",
            "COST_FLOOR_MISSING",
            cost_floor_bps=None,
            net_room_bps=None,
            **common,
        )
    cost_floor = float(cost_floor_bps)
    if cost_floor < 0.0:
        raise ValueError("cost_floor_bps must be >= 0")
    net_room = gross_room - cost_floor
    if net_room < float(config.min_net_room_bps):
        return _result(
            world_event,
            target,
            decision,
            "REJECTED",
            "COSTS_ERASE_EDGE",
            cost_floor_bps=cost_floor,
            net_room_bps=net_room,
            **common,
        )

    return _result(
        world_event,
        target,
        decision,
        "CANDIDATE",
        "EVENT_CONFIRMED_EXECUTABLE_LAG",
        cost_floor_bps=cost_floor,
        net_room_bps=net_room,
        **common,
    )


def _event_quality_reason(
    row: WorldMonitorEvent,
    config: EventLeadLagConfig,
) -> str | None:
    if (
        float(row.event.classification_confidence)
        < float(config.min_event_confidence)
    ):
        return "EVENT_CONFIDENCE_TOO_LOW"
    if row.event.corroboration_count < int(config.min_corroboration_count):
        return "INSUFFICIENT_CORROBORATION"

    if row.kind == "news":
        if row.importance_score is None:
            return "NEWS_IMPORTANCE_MISSING"
        if float(row.importance_score) < float(config.min_news_importance):
            return "NEWS_IMPORTANCE_TOO_LOW"
        if row.credibility_score is None:
            return "NEWS_CREDIBILITY_MISSING"
        if float(row.credibility_score) < float(config.min_news_credibility):
            return "NEWS_CREDIBILITY_TOO_LOW"
    elif row.kind == "prediction":
        if row.probability_delta_pp is None:
            return "PREDICTION_DELTA_MISSING"
        if abs(float(row.probability_delta_pp)) < float(config.min_prediction_delta_pp):
            return "PREDICTION_DELTA_TOO_SMALL"
    elif row.kind == "cross_source":
        severity = row.event.severity
        if severity is None:
            return "CROSS_SOURCE_SEVERITY_MISSING"
        if float(severity) < float(config.min_cross_source_severity):
            return "CROSS_SOURCE_SEVERITY_TOO_LOW"

    return None


def _result(
    row: WorldMonitorEvent,
    coin: str,
    decision_ts_ms: int,
    status: str,
    reason: str,
    *,
    event_age_ms: int,
    leader_venue: str | None = None,
    confirming_venues: tuple[str, ...] = (),
    research_direction: str | None = None,
    leader_move_bps: float | None = None,
    hyperliquid_mid_move_bps: float | None = None,
    hyperliquid_executable_move_bps: float | None = None,
    gross_room_bps: float | None = None,
    cost_floor_bps: float | None = None,
    net_room_bps: float | None = None,
    leader_snapshot_age_ms: int | None = None,
    hyperliquid_snapshot_age_ms: int | None = None,
) -> EventLeadLagCandidate:
    return EventLeadLagCandidate(
        event_id=row.event.event_id,
        event_kind=row.kind,
        coin=coin,
        decision_ts_ms=int(decision_ts_ms),
        status=status,
        reason=reason,
        event_age_ms=int(event_age_ms),
        leader_venue=leader_venue,
        confirming_venues=confirming_venues,
        research_direction=research_direction,
        leader_move_bps=leader_move_bps,
        hyperliquid_mid_move_bps=hyperliquid_mid_move_bps,
        hyperliquid_executable_move_bps=hyperliquid_executable_move_bps,
        gross_room_bps=gross_room_bps,
        cost_floor_bps=cost_floor_bps,
        net_room_bps=net_room_bps,
        leader_snapshot_age_ms=leader_snapshot_age_ms,
        hyperliquid_snapshot_age_ms=hyperliquid_snapshot_age_ms,
        event_importance_score=row.importance_score,
        event_credibility_score=row.credibility_score,
        event_corroboration_count=row.event.corroboration_count,
        prediction_delta_pp=row.probability_delta_pp,
        real_execution=False,
    )


__all__ = [
    "EventLeadLagCandidate",
    "EventLeadLagConfig",
    "SCHEMA_VERSION",
    "evaluate_event_lead_lag_candidate",
]
