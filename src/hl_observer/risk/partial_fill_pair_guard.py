"""Guard against accepting a hedge when only one leg can fill."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PartialFillPairGuard:
    blocked: bool
    reason: str
    min_ratio: float


def guard_partial_fill_pair(*, leg_a_ratio: float, leg_b_ratio: float, min_ratio: float = 0.95) -> PartialFillPairGuard:
    ratio = min(float(leg_a_ratio), float(leg_b_ratio))
    blocked = ratio < float(min_ratio)
    return PartialFillPairGuard(blocked=blocked, reason="PARTIAL_PAIR_FILL" if blocked else "OK", min_ratio=round(ratio, 8))


__all__ = ["PartialFillPairGuard", "guard_partial_fill_pair"]
