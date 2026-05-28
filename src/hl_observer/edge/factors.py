from __future__ import annotations

import math
from hl_observer.utils.math import clamp


def compute_freshness_factor(age_ms: int, half_life_ms: float = 3500.0) -> float:
    """
    Calculates signal freshness using exponential decay.
    At age = 0, factor = 1.0.
    At age = half_life, factor = 0.5.
    """
    if age_ms < 0:
        return 1.0
    if half_life_ms <= 0:
        return 0.0
    return math.pow(2, -age_ms / half_life_ms)


def compute_liquidity_penalty(notional_usdc: float, depth_usdc: float) -> float:
    """
    Estimates a liquidity penalty in bps using a market impact model.
    Using a common square root model: impact = constant * sqrt(trade_size / daily_volume)
    But here we only have depth, so we use: impact_bps = (notional / depth) * 100 bps
    """
    if depth_usdc <= 0:
        return 100.0

    if notional_usdc <= 0:
        return 0.0

    # Professional models often use: penalty = (trade_size / depth) * (typical_spread / 2)
    # We use a simpler linear impact model for the MVP.
    ratio = notional_usdc / depth_usdc
    penalty = ratio * 100.0
    return clamp(penalty, 0.0, 100.0)


def compute_crowding_penalty(num_leaders: int, threshold: int = 3, penalty_per_leader: float = 3.0) -> float:
    """
    Penalizes signals if too many leaders are doing the same trade.
    """
    if num_leaders <= threshold:
        return 0.0
    return clamp((num_leaders - threshold) * penalty_per_leader, 0.0, 30.0)


def compute_adverse_selection_penalty(toxicity_score: float, market_volatility_bps: float = 20.0) -> float:
    """
    Penalizes signals from 'toxic' wallets.
    """
    penalty = toxicity_score * market_volatility_bps * 0.5
    return clamp(penalty, 0.0, 25.0)


def compute_delay_cost(age_ms: int, volatility_bps_per_sec: float = 0.2) -> float:
    """
    Estimates the cost of delay due to price movement.
    """
    age_sec = max(0, age_ms / 1000.0)
    return age_sec * volatility_bps_per_sec


def compute_funding_penalty(side: str, funding_rate: float, expected_hold_hours: float = 8.0) -> float:
    """
    Estimates funding cost in bps for the expected hold period.
    Hyperliquid funding is usually hourly but quoted as 1-hour or 8-hour rate.
    We assume the input funding_rate is the hourly rate.
    """
    # If funding is positive, longs pay shorts.
    direction = 1.0 if side.lower() == "long" else -1.0

    # Cost = direction * funding_rate * hold_time
    # funding_rate is usually small (e.g. 0.0001 for 1bp per hour)
    cost_bps = direction * funding_rate * expected_hold_hours * 10000.0

    # We only care about costs (positive penalty)
    return max(0.0, cost_bps)


def compute_gain_assurance_score(
    edge_remaining_bps: float,
    min_edge_required_bps: float,
    freshness_factor: float,
    consistency_factor: float,
    liquidity_score: float,
) -> float:
    """
    Summarizes the probability of replicating the leader's edge.
    """
    if edge_remaining_bps <= 0:
        return 0.0

    # Weighted components for a pro assessment
    # 1. Edge Buffer (30%): How much margin of error we have
    edge_buffer = clamp((edge_remaining_bps - min_edge_required_bps) / 20.0, 0.0, 1.0)

    # 2. Freshness (30%): Is the information still valid?
    # 3. Consistency (20%): Is the leader reliable?
    # 4. Liquidity (20%): Can we execute without being the market?

    score = (
        0.3 * edge_buffer * 100.0 +
        0.3 * freshness_factor * 100.0 +
        0.2 * clamp(consistency_factor, 0.0, 1.2) * 83.3 + # 1.2 -> ~100
        0.2 * liquidity_score
    )
    return clamp(score, 0.0, 100.0)
