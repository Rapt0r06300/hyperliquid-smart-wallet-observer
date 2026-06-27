"""V15 #202 — Pyramiding / scale-in on confirmation (add only when it goes our way)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PyramidDecision:
    add: bool
    reason: str


def pyramiding_decision(
    *,
    in_profit_bps: float,
    confirmation: bool,
    current_adds: int,
    max_adds: int = 2,
    min_profit_bps: float = 25.0,
) -> PyramidDecision:
    """Add to a winner only: in profit beyond a floor + fresh confirmation + under the add cap."""
    if current_adds >= max_adds:
        return PyramidDecision(False, "MAX_ADDS_REACHED")
    if in_profit_bps < min_profit_bps:
        return PyramidDecision(False, "NOT_ENOUGH_PROFIT")
    if not confirmation:
        return PyramidDecision(False, "NO_CONFIRMATION")
    return PyramidDecision(True, "ADD_ON_CONFIRMED_WINNER")


__all__ = ["PyramidDecision", "pyramiding_decision"]
