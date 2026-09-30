"""Observation-driven freshness policy (S6 — V9, PolyWeather A2).

Two responsibilities:
  1. Refuse signals that are too old (deny-by-default on uncertainty).
  2. Anti-jump patch merge: only apply a strictly newer, non-stale revision so
     the dashboard/state never flickers backwards.

SAFETY: pure. Missing timestamp -> refuse (we never assume freshness).
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class FreshnessAction(StrEnum):
    ACCEPT = "ACCEPT"
    REFUSE_STALE = "REFUSE_STALE"
    REFUSE_NO_TIMESTAMP = "REFUSE_NO_TIMESTAMP"


@dataclass(frozen=True, slots=True)
class FreshnessDecision:
    action: FreshnessAction
    age_ms: int | None
    max_age_ms: int
    fresh: bool
    reason: str


def evaluate_freshness(
    source_ts_ms: int | None,
    *,
    now_ms: int,
    max_age_ms: int,
) -> FreshnessDecision:
    """Decide whether a timestamped observation is fresh enough to act on."""
    if source_ts_ms is None or source_ts_ms <= 0:
        return FreshnessDecision(
            FreshnessAction.REFUSE_NO_TIMESTAMP, None, max_age_ms, False, "no source timestamp"
        )
    age = now_ms - int(source_ts_ms)
    if age < 0:
        # Clock skew / future timestamp: treat as fresh but clamp age to 0.
        age = 0
    if age > max_age_ms:
        return FreshnessDecision(
            FreshnessAction.REFUSE_STALE, age, max_age_ms, False, f"age_ms={age}>max={max_age_ms}"
        )
    return FreshnessDecision(FreshnessAction.ACCEPT, age, max_age_ms, True, "fresh")


def should_apply_patch(
    *,
    current_revision: int,
    incoming_revision: int,
    incoming_age_ms: int | None = None,
    max_age_ms: int | None = None,
) -> bool:
    """Anti-jump: apply only a strictly newer, non-stale revision."""
    if incoming_revision <= current_revision:
        return False
    if max_age_ms is not None and incoming_age_ms is not None and incoming_age_ms > max_age_ms:
        return False
    return True
