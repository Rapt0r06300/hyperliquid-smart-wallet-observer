"""Streak- and confidence-aware position sizing (S7 — V9, MrFadiAi A3 + CloddsBot).

base = 2% of equity. Each consecutive loss shrinks size by 20% (×0.8),
each consecutive win grows it by 10% (×1.1), hard-capped at 5% and floored
at 0.5%. A calibrated confidence in [0,1] scales the result (Brier-coupled).

SAFETY: returns a *paper* size only.
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_PCT = 2.0
CAP_PCT = 5.0
FLOOR_PCT = 0.5
LOSS_FACTOR = 0.8
WIN_FACTOR = 1.1


@dataclass(frozen=True, slots=True)
class SizingDecision:
    size_pct: float
    multiplier: float
    confidence: float
    capped: bool
    floored: bool


def compute_size_pct(
    *,
    consecutive_losses: int = 0,
    consecutive_wins: int = 0,
    base_pct: float = BASE_PCT,
    cap_pct: float = CAP_PCT,
    floor_pct: float = FLOOR_PCT,
    confidence: float = 1.0,
) -> SizingDecision:
    losses = max(0, consecutive_losses)
    wins = max(0, consecutive_wins)
    conf = min(1.0, max(0.0, confidence))

    multiplier = (LOSS_FACTOR ** losses) * (WIN_FACTOR ** wins)
    raw = base_pct * multiplier * conf

    capped = raw > cap_pct
    floored = raw < floor_pct
    size = min(cap_pct, max(floor_pct, raw))
    # A zero confidence collapses size to floor only if we still want exposure;
    # confidence==0 should mean no size.
    if conf <= 0.0:
        size = 0.0
        floored = False
    return SizingDecision(
        size_pct=size,
        multiplier=multiplier,
        confidence=conf,
        capped=capped,
        floored=floored,
    )


def size_to_notional(size_pct: float, equity_usdc: float) -> float:
    return max(0.0, size_pct) / 100.0 * max(0.0, equity_usdc)
