"""Liquidity cliff detector for paper entries."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class LiquidityRiskDecision:
    ok: bool
    top_depth_usdt: float
    next_depth_usdt: float
    cliff_ratio: float
    reason: str | None


def detect_liquidity_cliff(
    *,
    top_depth_usdt: float,
    next_depth_usdt: float,
    min_top_depth_usdt: float = 500.0,
    max_cliff_ratio: float = 4.0,
) -> LiquidityRiskDecision:
    top = max(0.0, float(top_depth_usdt or 0.0))
    nxt = max(0.0, float(next_depth_usdt or 0.0))
    if top < float(min_top_depth_usdt):
        return LiquidityRiskDecision(False, top, nxt, 0.0, "TOP_DEPTH_TOO_LOW")
    ratio = top / max(1e-9, nxt)
    if ratio > float(max_cliff_ratio):
        return LiquidityRiskDecision(False, top, nxt, round(ratio, 8), "LIQUIDITY_CLIFF")
    return LiquidityRiskDecision(True, top, nxt, round(ratio, 8), None)


def fleeting_liquidity_receipt(rows: Iterable[Mapping[str, object]], *, max_lifetime_ms: int = 1_000) -> dict[str, object]:
    """Identify displayed liquidity that vanishes quickly without inventing a fill."""

    observed: list[tuple[int, float]] = []
    for row in rows:
        try:
            ts, notional = row["ts_ms"], float(row["notional_usdt"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return {"status": "UNMEASURABLE", "reason": "OBSERVATION_INVALID"}
        if type(ts) is not int or ts <= 0 or not math.isfinite(notional) or notional < 0.0:
            return {"status": "UNMEASURABLE", "reason": "OBSERVATION_INVALID"}
        observed.append((ts, notional))
    if len(observed) < 2 or isinstance(max_lifetime_ms, bool) or max_lifetime_ms < 0:
        return {"status": "UNMEASURABLE", "reason": "OBSERVATIONS_INSUFFICIENT"}
    observed.sort(key=lambda item: item[0])
    lifetime = observed[-1][0] - observed[0][0]
    fugitive = observed[0][1] > 0.0 and observed[-1][1] == 0.0 and lifetime <= max_lifetime_ms
    return {"status": "PROVEN", "fugitive": fugitive, "lifetime_ms": lifetime, "reason": "FLEETING_LIQUIDITY" if fugitive else "PERSISTENT_OR_NOT_OBSERVED"}


__all__ = ["LiquidityRiskDecision", "detect_liquidity_cliff", "fleeting_liquidity_receipt"]
