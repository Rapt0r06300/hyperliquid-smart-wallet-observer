"""Margin-of-safety gate for paper opportunities.

The idea appears in many mature trading frameworks: an apparent edge is not
enough; it must remain large after fees, spread, slippage, latency and funding.
This module is pure arithmetic and never emits an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MarginOfSafetyConfig:
    min_net_edge_bps: float = 8.0
    min_cost_coverage_ratio: float = 1.35
    min_margin_bps: float = 4.0


@dataclass(frozen=True, slots=True)
class MarginOfSafetyDecision:
    accepted: bool
    gross_edge_bps: float
    total_cost_bps: float
    net_edge_bps: float
    cost_coverage_ratio: float
    margin_bps: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def evaluate_margin_of_safety(
    *,
    gross_edge_bps: float,
    total_cost_bps: float,
    config: MarginOfSafetyConfig | None = None,
) -> MarginOfSafetyDecision:
    cfg = config or MarginOfSafetyConfig()
    gross = float(gross_edge_bps or 0.0)
    costs = max(0.0, float(total_cost_bps or 0.0))
    net = gross - costs
    ratio = gross / costs if costs > 0 else float("inf")
    margin = net - float(cfg.min_net_edge_bps)
    reasons: list[str] = []
    if gross <= 0:
        reasons.append("GROSS_EDGE_MISSING")
    if net < cfg.min_net_edge_bps:
        reasons.append("NET_EDGE_BELOW_MINIMUM")
    if ratio < cfg.min_cost_coverage_ratio:
        reasons.append("COST_COVERAGE_TOO_LOW")
    if margin < cfg.min_margin_bps:
        reasons.append("MARGIN_OF_SAFETY_TOO_LOW")
    return MarginOfSafetyDecision(
        accepted=not reasons,
        gross_edge_bps=round(gross, 8),
        total_cost_bps=round(costs, 8),
        net_edge_bps=round(net, 8),
        cost_coverage_ratio=round(ratio, 8) if ratio != float("inf") else ratio,
        margin_bps=round(margin, 8),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


__all__ = ["MarginOfSafetyConfig", "MarginOfSafetyDecision", "evaluate_margin_of_safety"]
