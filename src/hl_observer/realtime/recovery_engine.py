from __future__ import annotations

from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass


class StreamEventType(StrEnum):
    NEW = "NEW"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    FLIP = "FLIP"
    DATA_GAP = "DATA_GAP"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"
    SNAPSHOT = "SNAPSHOT"


class RecoveryAction(StrEnum):
    KEEP_WATCHING = "KEEP_WATCHING"
    RECONNECT = "RECONNECT"
    BACKFILL = "BACKFILL"
    RECONNECT_AND_BACKFILL = "RECONNECT_AND_BACKFILL"
    DROP_DUPLICATE = "DROP_DUPLICATE"
    OBSERVE_ONLY = "OBSERVE_ONLY"


@dataclass(frozen=True, slots=True)
class WatchStreamEvent:
    event_id: str
    wallet_address: str
    observed_at_ms: int
    received_at_ms: int
    event_type: StreamEventType = StreamEventType.NEW
    sequence: int | None = None
    is_snapshot: bool = False
    payload_hash: str | None = None


@dataclass(slots=True)
class WatchState:
    wallet_address: str
    last_event_at_ms: int | None = None
    last_received_at_ms: int | None = None
    last_sequence: int | None = None
    seen_event_ids: set[str] = field(default_factory=set)
    seen_payload_hashes: set[str] = field(default_factory=set)
    stale_count: int = 0
    duplicate_count: int = 0
    gap_count: int = 0
    reconnect_count: int = 0


@dataclass(frozen=True, slots=True)
class BackfillRequestPlan:
    wallet_address: str
    start_time_ms: int
    end_time_ms: int
    reason: str
    max_pages: int
    network_required: bool = True


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    wallet_address: str
    action: RecoveryAction
    reason: str
    event_type: StreamEventType
    accepted_for_signal: bool
    should_reconnect: bool = False
    backfill: BackfillRequestPlan | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    stale_after_ms: int = 20_000
    max_event_gap_ms: int = 5_000
    max_sequence_gap: int = 1
    backfill_overlap_ms: int = 1_000
    max_backfill_window_ms: int = 300_000
    max_pages: int = 3


class RealtimeRecoveryEngine:
    def __init__(self, policy: ReconnectPolicy | None = None) -> None:
        self.policy = policy or ReconnectPolicy()
        self.states: dict[str, WatchState] = {}

    def state_for(self, wallet_address: str) -> WatchState:
        key = wallet_address.lower()
        state = self.states.get(key)
        if state is None:
            state = WatchState(wallet_address=key)
            self.states[key] = state
        return state

    def process_event(self, event: WatchStreamEvent) -> RecoveryDecision:
        state = self.state_for(event.wallet_address)
        warnings: list[str] = []
        if event.event_id in state.seen_event_ids or (event.payload_hash and event.payload_hash in state.seen_payload_hashes):
            state.duplicate_count += 1
            return RecoveryDecision(
                wallet_address=state.wallet_address,
                action=RecoveryAction.DROP_DUPLICATE,
                reason="DUPLICATE_EVENT",
                event_type=StreamEventType.DUPLICATE,
                accepted_for_signal=False,
                warnings=("DUPLICATE_EVENT",),
            )

        if event.is_snapshot or event.event_type == StreamEventType.SNAPSHOT:
            self._remember(state, event)
            return RecoveryDecision(
                wallet_address=state.wallet_address,
                action=RecoveryAction.OBSERVE_ONLY,
                reason="SNAPSHOT_CONTEXT_ONLY",
                event_type=StreamEventType.SNAPSHOT,
                accepted_for_signal=False,
            )

        gap_ms = None if state.last_event_at_ms is None else event.observed_at_ms - state.last_event_at_ms
        sequence_gap = None
        if event.sequence is not None and state.last_sequence is not None:
            sequence_gap = event.sequence - state.last_sequence

        if gap_ms is not None and gap_ms > self.policy.max_event_gap_ms:
            state.gap_count += 1
            warnings.append("DATA_GAP_BY_TIME")
        if sequence_gap is not None and sequence_gap > self.policy.max_sequence_gap:
            state.gap_count += 1
            warnings.append("DATA_GAP_BY_SEQUENCE")

        stale_age_ms = event.received_at_ms - event.observed_at_ms
        if stale_age_ms > self.policy.stale_after_ms:
            state.stale_count += 1
            warnings.append("STALE_EVENT")

        backfill = None
        if warnings:
            backfill = self._build_backfill(state.wallet_address, event, reason="|".join(warnings))
            state.reconnect_count += 1
            self._remember(state, event)
            return RecoveryDecision(
                wallet_address=state.wallet_address,
                action=RecoveryAction.RECONNECT_AND_BACKFILL,
                reason="|".join(warnings),
                event_type=StreamEventType.DATA_GAP if any("DATA_GAP" in item for item in warnings) else StreamEventType.STALE,
                accepted_for_signal=False,
                should_reconnect=True,
                backfill=backfill,
                warnings=tuple(sorted(set(warnings))),
            )

        self._remember(state, event)
        return RecoveryDecision(
            wallet_address=state.wallet_address,
            action=RecoveryAction.KEEP_WATCHING,
            reason="EVENT_FRESH_AND_ORDERED",
            event_type=event.event_type,
            accepted_for_signal=True,
        )

    def evaluate_idle_wallet(self, wallet_address: str, *, now_ms: int) -> RecoveryDecision:
        state = self.state_for(wallet_address)
        if state.last_received_at_ms is None:
            return RecoveryDecision(
                wallet_address=state.wallet_address,
                action=RecoveryAction.RECONNECT,
                reason="NO_EVENTS_YET",
                event_type=StreamEventType.STALE,
                accepted_for_signal=False,
                should_reconnect=True,
            )
        idle_ms = now_ms - state.last_received_at_ms
        if idle_ms <= self.policy.stale_after_ms:
            return RecoveryDecision(
                wallet_address=state.wallet_address,
                action=RecoveryAction.KEEP_WATCHING,
                reason="WATCH_HEALTHY",
                event_type=StreamEventType.NEW,
                accepted_for_signal=False,
            )
        fake_event = WatchStreamEvent(
            event_id=f"idle:{state.wallet_address}:{now_ms}",
            wallet_address=state.wallet_address,
            observed_at_ms=state.last_event_at_ms or state.last_received_at_ms,
            received_at_ms=now_ms,
            event_type=StreamEventType.STALE,
        )
        state.stale_count += 1
        state.reconnect_count += 1
        return RecoveryDecision(
            wallet_address=state.wallet_address,
            action=RecoveryAction.RECONNECT_AND_BACKFILL,
            reason="WATCH_IDLE_STALE",
            event_type=StreamEventType.STALE,
            accepted_for_signal=False,
            should_reconnect=True,
            backfill=self._build_backfill(state.wallet_address, fake_event, reason="WATCH_IDLE_STALE"),
            warnings=("WATCH_IDLE_STALE",),
        )

    def _build_backfill(self, wallet_address: str, event: WatchStreamEvent, *, reason: str) -> BackfillRequestPlan:
        end_time = max(0, event.observed_at_ms)
        start_time = max(0, end_time - self.policy.max_backfill_window_ms)
        if self.policy.backfill_overlap_ms:
            start_time = max(0, start_time - self.policy.backfill_overlap_ms)
        return BackfillRequestPlan(
            wallet_address=wallet_address,
            start_time_ms=start_time,
            end_time_ms=end_time + 1,
            reason=reason,
            max_pages=self.policy.max_pages,
        )

    def _remember(self, state: WatchState, event: WatchStreamEvent) -> None:
        state.seen_event_ids.add(event.event_id)
        if event.payload_hash:
            state.seen_payload_hashes.add(event.payload_hash)
        state.last_event_at_ms = max(state.last_event_at_ms or 0, event.observed_at_ms)
        state.last_received_at_ms = max(state.last_received_at_ms or 0, event.received_at_ms)
        if event.sequence is not None:
            state.last_sequence = max(state.last_sequence or event.sequence, event.sequence)


def format_recovery_decision(decision: RecoveryDecision) -> str:
    lines = [
        "realtime_recovery=read_only",
        f"wallet={decision.wallet_address}",
        f"action={decision.action.value}",
        f"reason={decision.reason}",
        f"event_type={decision.event_type.value}",
        f"accepted_for_signal={str(decision.accepted_for_signal).lower()}",
        f"should_reconnect={str(decision.should_reconnect).lower()}",
    ]
    if decision.backfill:
        lines.extend(
            [
                f"backfill_wallet={decision.backfill.wallet_address}",
                f"backfill_window={decision.backfill.start_time_ms}->{decision.backfill.end_time_ms}",
                f"backfill_reason={decision.backfill.reason}",
                f"backfill_max_pages={decision.backfill.max_pages}",
            ]
        )
    lines.append(f"warnings={','.join(decision.warnings) if decision.warnings else 'OK'}")
    lines.append("execution=forbidden")
    lines.append("profit_guarantee=false")
    return "\n".join(lines)
