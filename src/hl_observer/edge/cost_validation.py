"""Edge remaining and cost validation with strict gates."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Cost multiplier threshold: reject if fees > 3x expected edge
COST_MULTIPLIER_SAFETY_THRESHOLD = 3.0

# Minimum edge required in basis points
MIN_EDGE_REQUIRED_BPS = 30.0


@dataclass(frozen=True)
class EdgeValidation:
    """Result of edge remaining validation."""

    passed: bool
    reason: str
    edge_remaining_bps: float | None = None
    total_costs_bps: float | None = None
    cost_to_edge_ratio: float | None = None


def validate_edge_remaining(
    edge_remaining_bps: float,
    total_costs_bps: float,
    min_edge_required_bps: float = MIN_EDGE_REQUIRED_BPS,
) -> EdgeValidation:
    """
    Validate edge remaining is sufficient to cover all costs.

    Rules:
    1. edge_remaining must be > 0
    2. edge_remaining >= min_edge_required_bps
    3. total_costs must be < min_edge_required_bps * COST_MULTIPLIER_SAFETY_THRESHOLD
       i.e., costs cannot exceed 3x minimum expected edge

    Args:
        edge_remaining_bps: Edge after all costs
        total_costs_bps: Sum of all costs (fees, spread, slippage, etc)
        min_edge_required_bps: Minimum edge threshold

    Returns:
        EdgeValidation with pass/fail and details
    """
    # Edge must be positive
    if edge_remaining_bps <= 0:
        return EdgeValidation(
            passed=False,
            reason=f"EDGE_REMAINING_NEGATIVE_OR_ZERO_{edge_remaining_bps:.2f}_BPS",
            edge_remaining_bps=edge_remaining_bps,
            total_costs_bps=total_costs_bps,
        )

    # Edge must meet minimum threshold
    if edge_remaining_bps < min_edge_required_bps:
        return EdgeValidation(
            passed=False,
            reason=f"EDGE_REMAINING_{edge_remaining_bps:.2f}_BELOW_MINIMUM_{min_edge_required_bps:.2f}",
            edge_remaining_bps=edge_remaining_bps,
            total_costs_bps=total_costs_bps,
        )

    # Cost multiplier safety check: costs must not be disproportionate to edge
    max_allowable_cost = min_edge_required_bps * COST_MULTIPLIER_SAFETY_THRESHOLD
    if total_costs_bps > max_allowable_cost:
        cost_to_edge = total_costs_bps / min_edge_required_bps if min_edge_required_bps > 0 else float('inf')
        return EdgeValidation(
            passed=False,
            reason=f"COSTS_{total_costs_bps:.2f}_EXCEED_SAFETY_LIMIT_{max_allowable_cost:.2f}_RATIO_{cost_to_edge:.2f}X",
            edge_remaining_bps=edge_remaining_bps,
            total_costs_bps=total_costs_bps,
            cost_to_edge_ratio=cost_to_edge,
        )

    # All checks passed
    cost_to_edge = total_costs_bps / edge_remaining_bps if edge_remaining_bps > 0 else 0
    return EdgeValidation(
        passed=True,
        reason=f"EDGE_SUFFICIENT_{edge_remaining_bps:.2f}_BPS_COSTS_{total_costs_bps:.2f}_RATIO_{cost_to_edge:.2f}X",
        edge_remaining_bps=edge_remaining_bps,
        total_costs_bps=total_costs_bps,
        cost_to_edge_ratio=cost_to_edge,
    )


def estimate_total_costs(
    taker_fee_bps: float = 0.0,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
    latency_bps: float = 0.0,
    adverse_selection_bps: float = 0.0,
    funding_cost_bps: float = 0.0,
) -> float:
    """
    Calculate total expected costs in basis points.

    Args:
        taker_fee_bps: Taker fee (typically ~2.5 bps maker, 5-7.5 bps taker)
        spread_bps: Bid-ask spread (order book depth dependent)
        slippage_bps: Estimated execution slippage
        latency_bps: Latency cost (time to execute vs fill)
        adverse_selection_bps: Risk of leader dumping before copy executes
        funding_cost_bps: Funding rate exposure

    Returns:
        Total costs in basis points (can exceed 100 bps)
    """
    return (
        taker_fee_bps
        + spread_bps
        + slippage_bps
        + latency_bps
        + adverse_selection_bps
        + funding_cost_bps
    )


def categorize_cost_level(total_costs_bps: float) -> str:
    """Categorize cost level by severity."""
    if total_costs_bps <= 5:
        return "VERY_LOW"
    elif total_costs_bps <= 15:
        return "LOW"
    elif total_costs_bps <= 30:
        return "MODERATE"
    elif total_costs_bps <= 60:
        return "HIGH"
    elif total_costs_bps <= 100:
        return "VERY_HIGH"
    else:
        return "PROHIBITIVE"


def suggest_cost_reduction_actions(total_costs_bps: float, edge_remaining_bps: float) -> list[str]:
    """
    Suggest cost reduction actions if edge is marginal.

    Returns:
        List of actionable suggestions
    """
    suggestions = []

    if total_costs_bps > 100:
        suggestions.append("REJECT_ILLIQUID_COINS_HIGH_SPREAD")

    if edge_remaining_bps < 30 and total_costs_bps > 50:
        suggestions.append("REQUIRE_MINIMUM_NOTIONAL_SIZE_TO_AMORTIZE_FEES")
        suggestions.append("INCREASE_WALLET_SCORE_THRESHOLD")

    if edge_remaining_bps < 0:
        suggestions.append("REJECT_SIGNAL_EDGE_DESTROYED_BY_COSTS")
        suggestions.append("STRENGTHEN_EDGE_DETECTION_SIGNAL_FILTERING")

    if total_costs_bps > edge_remaining_bps * 2:
        suggestions.append("INCREASE_MIN_EDGE_REQUIRED_TO_2X_COSTS_MINIMUM")

    return suggestions
