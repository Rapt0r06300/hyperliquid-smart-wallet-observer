from __future__ import annotations

from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from hl_observer.models import Fill


class LifecycleAction(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    ADD = "ADD"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    FLIP = "FLIP"
    LIQUIDATION = "LIQUIDATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    wallet: str
    coin: str
    action: LifecycleAction
    previous_size: float
    current_size: float
    size_delta: float
    time_ms: int
    price: float | None = None
    closed_pnl: float | None = None
    fee: float | None = None
    confidence: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleEpisode:
    wallet: str
    coin: str
    events: tuple[LifecycleEvent, ...]
    status: str
    confidence: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def classify_lifecycle_delta(
    previous_size: float,
    current_size: float,
    *,
    liquidation: bool = False,
    epsilon: float = 1e-12,
) -> LifecycleAction:
    if liquidation:
        return LifecycleAction.LIQUIDATION
    prev = _zero_small(previous_size, epsilon)
    cur = _zero_small(current_size, epsilon)
    if prev == cur:
        return LifecycleAction.UNKNOWN
    if prev == 0 and cur > 0:
        return LifecycleAction.OPEN_LONG
    if prev == 0 and cur < 0:
        return LifecycleAction.OPEN_SHORT
    if prev > 0 and cur > 0:
        return LifecycleAction.INCREASE if cur > prev else LifecycleAction.REDUCE
    if prev < 0 and cur < 0:
        return LifecycleAction.INCREASE if abs(cur) > abs(prev) else LifecycleAction.REDUCE
    if prev > 0 and cur == 0:
        return LifecycleAction.CLOSE_LONG
    if prev < 0 and cur == 0:
        return LifecycleAction.CLOSE_SHORT
    if (prev > 0 and cur < 0) or (prev < 0 and cur > 0):
        return LifecycleAction.FLIP
    return LifecycleAction.UNKNOWN


def event_from_fill(fill: Fill, *, fallback_previous_size: float = 0.0) -> LifecycleEvent:
    direction = (fill.direction or "").strip().lower()
    liquidation = "liquid" in direction
    previous = fill.start_position
    warnings: list[str] = []
    if previous is None:
        previous = fallback_previous_size
        warnings.append("START_POSITION_MISSING_USED_RUNNING_POSITION")
    signed_delta = _signed_delta(fill)
    if signed_delta is None:
        action = LifecycleAction.UNKNOWN
        current = float(previous)
        warnings.append("FILL_SIGN_UNDETERMINED")
        confidence = 0.0
    else:
        current = float(previous) + signed_delta
        action = classify_lifecycle_delta(float(previous), current, liquidation=liquidation)
        confidence = _confidence_for(action, fill, warnings)
        if action == LifecycleAction.FLIP:
            warnings.append("FLIP_NEEDS_SPLIT_NO_DIRECT_PAPER_INTENT")
        if action == LifecycleAction.UNKNOWN:
            warnings.append("UNKNOWN_LIFECYCLE_NO_PAPER_INTENT")
    return LifecycleEvent(
        wallet=fill.wallet,
        coin=fill.coin,
        action=action,
        previous_size=float(previous),
        current_size=current,
        size_delta=current - float(previous),
        time_ms=fill.time_ms,
        price=fill.price,
        closed_pnl=fill.closed_pnl,
        fee=fill.fee,
        confidence=confidence,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_ref=fill.fill_hash or fill.tid or fill.oid,
    )


def reconstruct_lifecycles(wallet: str, fills: list[Fill]) -> list[LifecycleEpisode]:
    running_by_coin: dict[str, float] = {}
    events_by_coin: dict[str, list[LifecycleEvent]] = {}
    for fill in sorted(fills, key=lambda item: item.time_ms):
        if fill.wallet.lower() != wallet.lower():
            continue
        fallback = running_by_coin.get(fill.coin, 0.0)
        event = event_from_fill(fill, fallback_previous_size=fallback)
        running_by_coin[fill.coin] = event.current_size
        events_by_coin.setdefault(fill.coin, []).append(event)

    episodes: list[LifecycleEpisode] = []
    for coin, events in sorted(events_by_coin.items()):
        warnings = tuple(w for event in events for w in event.warnings)
        confidence = sum(event.confidence for event in events) / len(events) if events else 0.0
        status = "OPEN" if events and _zero_small(events[-1].current_size) != 0 else "CLOSED"
        if warnings:
            status = "PARTIAL_WITH_WARNINGS"
        episodes.append(
            LifecycleEpisode(
                wallet=wallet.lower(),
                coin=coin,
                events=tuple(events),
                status=status,
                confidence=round(confidence, 4),
                warnings=warnings,
            )
        )
    return episodes


def _signed_delta(fill: Fill) -> float | None:
    direction = (fill.direction or "").strip().lower()
    if "open long" in direction or "close short" in direction:
        return abs(fill.size)
    if "open short" in direction or "close long" in direction:
        return -abs(fill.size)
    side = (fill.side or "").strip().lower()
    if side in {"b", "buy", "bid"}:
        return abs(fill.size)
    if side in {"a", "s", "sell", "ask"}:
        return -abs(fill.size)
    return None


def _confidence_for(action: LifecycleAction, fill: Fill, warnings: list[str]) -> float:
    if action in {LifecycleAction.UNKNOWN, LifecycleAction.FLIP}:
        return 0.0 if action == LifecycleAction.UNKNOWN else 0.2
    base = 0.92 if fill.start_position is not None else 0.62
    if warnings:
        base -= 0.15
    if fill.meta.is_stale:
        base = min(base, 0.25)
    return max(0.0, min(1.0, base))


def _zero_small(value: float, epsilon: float = 1e-12) -> float:
    value = float(value)
    return 0.0 if abs(value) <= epsilon else value


__all__ = [
    "LifecycleAction",
    "LifecycleEpisode",
    "LifecycleEvent",
    "classify_lifecycle_delta",
    "event_from_fill",
    "reconstruct_lifecycles",
]
