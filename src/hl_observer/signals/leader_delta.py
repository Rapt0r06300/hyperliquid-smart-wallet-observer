from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from hl_observer.position_lifecycle.reconstructor import LifecycleAction, LifecycleEvent


ENTRY_ACTIONS = {
    LifecycleAction.OPEN_LONG,
    LifecycleAction.OPEN_SHORT,
    LifecycleAction.ADD,
    LifecycleAction.INCREASE,
}


@dataclass(frozen=True, slots=True)
class LeaderDelta:
    delta_id: str
    wallet: str
    coin: str
    action: LifecycleAction
    previous_size: float
    current_size: float
    delta_size: float
    observed_at_ms: int
    leader_event_time_ms: int | None
    source: str
    confidence: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    evidence_ref: str | None = None

    @property
    def is_entry(self) -> bool:
        return self.action in ENTRY_ACTIONS

    @property
    def is_exit_or_reduce(self) -> bool:
        return self.action in {LifecycleAction.REDUCE, LifecycleAction.CLOSE_LONG, LifecycleAction.CLOSE_SHORT}

    @property
    def safe_for_paper_candidate(self) -> bool:
        return self.is_entry and self.confidence > 0 and not self.reason_codes


def leader_delta_from_lifecycle_event(
    event: LifecycleEvent,
    *,
    observed_at_ms: int,
    source: str = "position_lifecycle",
) -> LeaderDelta:
    reasons: list[str] = list(event.warnings)
    if event.action in {LifecycleAction.UNKNOWN, LifecycleAction.FLIP, LifecycleAction.LIQUIDATION}:
        reasons.append(f"{event.action.value}_NO_DIRECT_PAPER_ENTRY")
    delta_id = _delta_id(
        event.wallet,
        event.coin,
        event.action.value,
        event.previous_size,
        event.current_size,
        event.time_ms,
        event.evidence_ref,
    )
    return LeaderDelta(
        delta_id=delta_id,
        wallet=event.wallet,
        coin=event.coin,
        action=event.action,
        previous_size=event.previous_size,
        current_size=event.current_size,
        delta_size=event.size_delta,
        observed_at_ms=observed_at_ms,
        leader_event_time_ms=event.time_ms,
        source=source,
        confidence=event.confidence,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence_ref=event.evidence_ref,
    )


def _delta_id(
    wallet: str,
    coin: str,
    action: str,
    previous_size: float,
    current_size: float,
    time_ms: int,
    evidence_ref: str | None,
) -> str:
    material = "|".join(
        str(part)
        for part in (
            wallet.lower(),
            coin.upper(),
            action,
            previous_size,
            current_size,
            time_ms,
            evidence_ref or "",
        )
    )
    return "ld:" + sha256(material.encode("utf-8")).hexdigest()


__all__ = ["ENTRY_ACTIONS", "LeaderDelta", "leader_delta_from_lifecycle_event"]
