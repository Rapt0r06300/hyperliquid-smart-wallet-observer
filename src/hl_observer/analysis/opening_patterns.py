from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass
from math import sqrt

from pydantic import BaseModel, Field

from hl_observer.utils.math import clamp


class OpeningPatternDecision(StrEnum):
    STRONG_OBSERVE = "STRONG_OBSERVE"
    PAPER_FOLLOW_ALLOWED = "PAPER_FOLLOW_ALLOWED"
    TESTNET_FOLLOW_CANDIDATE = "TESTNET_FOLLOW_CANDIDATE"
    REJECT_TOO_FEW_SAMPLES = "REJECT_TOO_FEW_SAMPLES"
    REJECT_NEGATIVE_EXPECTANCY = "REJECT_NEGATIVE_EXPECTANCY"
    REJECT_LOW_CONFIDENCE = "REJECT_LOW_CONFIDENCE"
    REJECT_TOO_LATE_TO_COPY = "REJECT_TOO_LATE_TO_COPY"
    REJECT_TOO_ILLIQUID = "REJECT_TOO_ILLIQUID"
    REJECT_TOO_VOLATILE = "REJECT_TOO_VOLATILE"
    REJECT_TOO_MUCH_DRAWDOWN = "REJECT_TOO_MUCH_DRAWDOWN"
    OBSERVE_ONLY = "OBSERVE_ONLY"


class OpeningPatternStats(BaseModel):
    wallet_address: str | None = None
    coin: str | None = None
    opening_type: str
    sample_size: int
    win_rate: float | None = None
    wilson_lower_bound: float | None = None
    expectancy: float | None = None
    profit_factor: float | None = None
    average_win: float | None = None
    average_loss: float | None = None
    score: float = 0.0
    decision: OpeningPatternDecision = OpeningPatternDecision.OBSERVE_ONLY
    reasons: list[str] = Field(default_factory=list)


def compute_opening_pattern_stats(
    pnls: list[float],
    *,
    opening_type: str,
    wallet_address: str | None = None,
    coin: str | None = None,
    min_samples: int = 20,
) -> OpeningPatternStats:
    sample = len(pnls)
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    win_rate = len(wins) / sample if sample else None
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    expectancy = (sum(pnls) / sample) if sample else None
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (None if not wins else 999.0)
    wilson = _wilson_lower_bound(len(wins), sample) if sample else None
    reasons: list[str] = []
    decision = OpeningPatternDecision.OBSERVE_ONLY
    if sample < min_samples:
        decision = OpeningPatternDecision.REJECT_TOO_FEW_SAMPLES
        reasons.append("sample_size_too_low")
    elif expectancy is not None and expectancy <= 0:
        decision = OpeningPatternDecision.REJECT_NEGATIVE_EXPECTANCY
        reasons.append("expectancy_non_positive")
    elif (wilson or 0) < 0.45:
        decision = OpeningPatternDecision.REJECT_LOW_CONFIDENCE
        reasons.append("wilson_lower_bound_low")
    else:
        decision = OpeningPatternDecision.PAPER_FOLLOW_ALLOWED
        reasons.append("positive_expectancy_with_sample")
    score = clamp(
        0.20 * clamp((expectancy or 0) / 100.0 * 100.0, 0.0, 100.0)
        + 0.18 * clamp((profit_factor or 0) / 3.0 * 100.0, 0.0, 100.0)
        + 0.15 * clamp((wilson or 0) * 100.0, 0.0, 100.0)
        + 0.12 * clamp(sample / min_samples * 100.0, 0.0, 100.0)
        + 0.35 * 50.0,
        0.0,
        100.0,
    )
    return OpeningPatternStats(
        wallet_address=wallet_address,
        coin=coin.upper() if coin else None,
        opening_type=opening_type,
        sample_size=sample,
        win_rate=win_rate,
        wilson_lower_bound=wilson,
        expectancy=expectancy,
        profit_factor=profit_factor,
        average_win=avg_win,
        average_loss=avg_loss,
        score=score,
        decision=decision,
        reasons=reasons,
    )


def _wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    phat = wins / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)
