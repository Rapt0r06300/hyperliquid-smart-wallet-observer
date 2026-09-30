"""Deep-sim fill outcomes (V12 capability P): partial fills, missed fills, funding.

Sits on top of exec_model (which gives queue_ratio / is_maker). A taker order fills
immediately; a maker order fills fully, partially, or not at all depending on its
queue position. Funding is charged over the holding time. Pure / deterministic:
no fabrication, no order — it models what a passive paper order would realistically get.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class FillOutcome(StrEnum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    MISSED = "MISSED"


@dataclass(frozen=True, slots=True)
class FillResult:
    outcome: FillOutcome
    fill_fraction: float          # 0..1
    filled_notional_usdc: float
    reason: str


def resolve_fill(
    *,
    notional_usdc: float,
    is_maker: bool,
    queue_ratio: float | None = None,
    queue_fill_threshold: float = 0.5,
) -> FillResult:
    """Decide how much of a paper order fills. Taker = immediate; maker = queue-dependent."""
    n = max(0.0, float(notional_usdc))
    if not is_maker:
        return FillResult(FillOutcome.FILLED, 1.0, n, "taker_immediate")
    if queue_ratio is None:
        # No book/queue data -> cannot trust a passive fill (deny-by-default): treat as missed.
        return FillResult(FillOutcome.MISSED, 0.0, 0.0, "maker_queue_unknown")
    q = float(queue_ratio)
    if q <= queue_fill_threshold:
        return FillResult(FillOutcome.FILLED, 1.0, n, f"queue_ratio={q:.3f}<=thr")
    if q < 1.0:
        frac = round(max(0.0, 1.0 - q), 6)
        return FillResult(FillOutcome.PARTIAL, frac, round(n * frac, 6), f"queue_ratio={q:.3f}")
    return FillResult(FillOutcome.MISSED, 0.0, 0.0, f"queue_ratio={q:.3f}>=1.0")


def funding_cost_bps(funding_rate_bps_per_hour: float, holding_ms: int) -> float:
    """Funding paid over the holding window, in bps (real rate × hours held)."""
    hours = max(0.0, float(holding_ms)) / 3_600_000.0
    return round(float(funding_rate_bps_per_hour) * hours, 6)


__all__ = ["FillOutcome", "FillResult", "resolve_fill", "funding_cost_bps"]
