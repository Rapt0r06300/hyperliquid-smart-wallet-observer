"""Local trailing-stop logic for paper positions only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrailingStopState:
    side: str
    entry_price: float
    best_price: float
    stop_price: float
    triggered: bool


def update_trailing_stop(state: TrailingStopState | None, *, side: str, entry_price: float, current_price: float, trail_bps: float) -> TrailingStopState:
    side_u = str(side).upper()
    trail = float(trail_bps) / 10_000.0
    if state is None:
        best = float(current_price)
    else:
        best = max(state.best_price, float(current_price)) if side_u == "LONG" else min(state.best_price, float(current_price))
    stop = best * (1 - trail) if side_u == "LONG" else best * (1 + trail)
    triggered = float(current_price) <= stop if side_u == "LONG" else float(current_price) >= stop
    return TrailingStopState(side=side_u, entry_price=float(entry_price), best_price=round(best, 10), stop_price=round(stop, 10), triggered=triggered)


__all__ = ["TrailingStopState", "update_trailing_stop"]
