"""V13 #154 — accumulate engine (mlmodelpoly): sliced entry + per-window caps (anti-churn)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AccumulateState:
    slices_in_window: int = 0
    usd_in_window: float = 0.0
    last_ts_ms: int = 0


def can_add_slice(state: AccumulateState, *, now_ms: int, slice_usd: float,
                  max_slices: int = 30, max_usd: float = 300.0,
                  cooldown_ms: int = 2000) -> tuple[bool, str | None]:
    if now_ms - state.last_ts_ms < cooldown_ms:
        return False, "COOLDOWN"
    if state.slices_in_window >= max_slices:
        return False, "MAX_SLICES_PER_WINDOW"
    if state.usd_in_window + float(slice_usd) > max_usd:
        return False, "MAX_USD_PER_WINDOW"
    return True, None


def apply_slice(state: AccumulateState, *, now_ms: int, slice_usd: float) -> AccumulateState:
    return AccumulateState(
        slices_in_window=state.slices_in_window + 1,
        usd_in_window=state.usd_in_window + float(slice_usd),
        last_ts_ms=int(now_ms),
    )


__all__ = ["AccumulateState", "can_add_slice", "apply_slice"]
