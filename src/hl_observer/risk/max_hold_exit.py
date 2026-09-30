"""Max-hold exit signal for paper positions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MaxHoldExitDecision:
    should_exit: bool
    hold_ms: int
    reason: str | None


def max_hold_exit(*, opened_at_ms: int, now_ms: int, max_hold_ms: int) -> MaxHoldExitDecision:
    hold = max(0, int(now_ms) - int(opened_at_ms))
    if hold >= int(max_hold_ms):
        return MaxHoldExitDecision(True, hold, "MAX_HOLD_EXIT")
    return MaxHoldExitDecision(False, hold, None)


__all__ = ["MaxHoldExitDecision", "max_hold_exit"]
