from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from hyper_smart_observer.copy_mode.copy_models import DeltaAction, LeaderDelta


@dataclass(frozen=True)
class PositionConsensus:
    coin: str
    direction: str
    wallet_count: int
    wallets: list[str]
    first_seen: datetime
    last_seen: datetime
    window_seconds: int
    consensus_score: float
    crowding_risk: str
    warnings: list[str] = field(default_factory=list)
    research_only_message: str = (
        "Consensus is a research observation only. It is not a guaranteed profit signal and not an order."
    )


def detect_position_consensus(
    deltas: Iterable[LeaderDelta | Any],
    *,
    min_wallets: int = 2,
    window_seconds: int = 300,
) -> list[PositionConsensus]:
    if min_wallets <= 0:
        raise ValueError("min_wallets must be positive")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    events = []
    for delta in deltas:
        action = _action(delta)
        current_size = _float_or_none(_value(delta, "current_size"))
        direction = direction_from_delta(action, current_size)
        if direction is None:
            continue
        observed_at = _datetime(_value(delta, "observed_at"))
        if observed_at is None:
            continue
        events.append(
            {
                "wallet": str(_value(delta, "leader_wallet")).lower(),
                "coin": str(_value(delta, "coin")).upper(),
                "direction": direction,
                "observed_at": observed_at,
            }
        )
    results: list[PositionConsensus] = []
    for key in sorted({(event["coin"], event["direction"]) for event in events}):
        group = sorted(
            [event for event in events if (event["coin"], event["direction"]) == key],
            key=lambda item: item["observed_at"],
        )
        best = _best_window(group, window_seconds)
        if len({event["wallet"] for event in best}) < min_wallets:
            continue
        wallets = sorted({event["wallet"] for event in best})
        first_seen = min(event["observed_at"] for event in best)
        last_seen = max(event["observed_at"] for event in best)
        span = max(0.0, (last_seen - first_seen).total_seconds())
        wallet_count = len(wallets)
        score = min(100.0, 45.0 + wallet_count * 18.0 + max(0.0, 1.0 - span / window_seconds) * 20.0)
        warnings = []
        crowding_risk = "LOW"
        if wallet_count >= 4:
            crowding_risk = "HIGH"
            warnings.append("crowding_risk_many_wallets_same_direction")
        elif wallet_count == 3:
            crowding_risk = "MEDIUM"
        results.append(
            PositionConsensus(
                coin=key[0],
                direction=key[1],
                wallet_count=wallet_count,
                wallets=wallets,
                first_seen=first_seen,
                last_seen=last_seen,
                window_seconds=window_seconds,
                consensus_score=round(score, 4),
                crowding_risk=crowding_risk,
                warnings=warnings,
            )
        )
    return sorted(results, key=lambda item: (item.wallet_count, item.consensus_score), reverse=True)


def direction_from_delta(action: DeltaAction | str, current_size: float | None = None) -> str | None:
    action_value = action.value if isinstance(action, DeltaAction) else str(action)
    if action_value == DeltaAction.OPEN_LONG.value:
        return "LONG"
    if action_value == DeltaAction.OPEN_SHORT.value:
        return "SHORT"
    if action_value in {DeltaAction.ADD.value, DeltaAction.INCREASE.value}:
        if current_size is None:
            return None
        if current_size > 0:
            return "LONG"
        if current_size < 0:
            return "SHORT"
    return None


def _best_window(group: list[dict[str, Any]], window_seconds: int) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    for index, event in enumerate(group):
        end = event["observed_at"] + timedelta(seconds=window_seconds)
        candidate = [item for item in group[index:] if item["observed_at"] <= end]
        if len({item["wallet"] for item in candidate}) > len({item["wallet"] for item in best}):
            best = candidate
    return best


def _value(delta: LeaderDelta | Any, key: str) -> Any:
    if isinstance(delta, dict):
        return delta.get(key)
    try:
        return delta[key]
    except (KeyError, TypeError, IndexError):
        return getattr(delta, key, None)


def _action(delta: LeaderDelta | Any) -> DeltaAction | str:
    value = _value(delta, "action_type")
    if isinstance(value, DeltaAction):
        return value
    try:
        return DeltaAction(str(value))
    except ValueError:
        return str(value)


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
