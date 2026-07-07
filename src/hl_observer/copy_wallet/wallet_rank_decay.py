"""Rank decay for watched wallets.

Top wallets are useful, but rank alone should decay with age and position. This
keeps fresh/high-ranked leaders privileged without treating stale rankings as a
permanent edge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RankDecayResult:
    base_score: float
    rank: int
    age_ms: int
    decay_factor: float
    decayed_score: float
    reason: str


def apply_wallet_rank_decay(
    *,
    base_score: float,
    rank: int,
    age_ms: int,
    rank_half_life: float = 50.0,
    age_half_life_ms: int = 6 * 60 * 60 * 1000,
) -> RankDecayResult:
    rank_value = max(1, int(rank or 1))
    age_value = max(0, int(age_ms or 0))
    rank_factor = math.exp(-max(0, rank_value - 1) / max(1.0, float(rank_half_life)))
    age_factor = 0.5 ** (age_value / max(1, int(age_half_life_ms)))
    factor = max(0.0, min(1.0, rank_factor * age_factor))
    score = max(0.0, min(1.0, float(base_score or 0.0) * factor))
    reason = "OK" if score > 0 else "RANK_DECAY_ZERO"
    return RankDecayResult(
        base_score=round(float(base_score or 0.0), 8),
        rank=rank_value,
        age_ms=age_value,
        decay_factor=round(factor, 8),
        decayed_score=round(score, 8),
        reason=reason,
    )


__all__ = ["RankDecayResult", "apply_wallet_rank_decay"]
