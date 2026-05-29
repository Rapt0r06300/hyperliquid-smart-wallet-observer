from __future__ import annotations

import math
from hl_observer.hyperliquid.schemas import WalletStyle
from hl_observer.utils.math import clamp


def compute_freshness_factor(age_ms: int, half_life_ms: float = 3500.0, volatility_index: float = 1.0) -> float:
    """
    Calculates signal freshness using exponential decay.
    At age = 0, factor = 1.0.
    At age = half_life, factor = 0.5.

    Volatility-adjusted: high volatility (index > 1.0) causes faster edge decay.
    """
    if age_ms < 0:
        return 1.0
    if half_life_ms <= 0:
        return 0.0

    # Adjust half-life by volatility. Higher volatility index -> shorter half-life.
    adjusted_half_life = half_life_ms / max(0.1, volatility_index)

    return math.pow(2, -age_ms / adjusted_half_life)


def compute_liquidity_penalty(notional_usdc: float, depth_usdc: float) -> float:
    """
    Estimates a liquidity penalty in bps using a market impact model.
    """
    if depth_usdc <= 0:
        return 100.0

    if notional_usdc <= 0:
        return 0.0

    # Impact = (trade_size / depth) * 100 bps
    ratio = notional_usdc / depth_usdc
    penalty = ratio * 100.0
    return clamp(penalty, 0.0, 100.0)


def compute_crowding_penalty(
    num_leaders: int,
    total_notional_usdc: float = 0.0,
    threshold_count: int = 3,
    threshold_notional: float = 50000.0
) -> float:
    """
    Penalizes signals if too many leaders or too much total notional is moving in the same direction.
    Crowding leads to rapid edge exhaustion and higher adverse selection.
    """
    if num_leaders <= threshold_count and total_notional_usdc < threshold_notional:
        return 0.0

    # Penalty from number of leaders: 3bps per leader above threshold
    count_penalty = max(0.0, (num_leaders - threshold_count) * 3.0)

    # Penalty from total size: 2bps per $100k of total leader notional
    size_penalty = (total_notional_usdc / 100000.0) * 2.0

    return clamp(count_penalty + size_penalty, 0.0, 40.0)


def compute_adverse_selection_penalty(
    toxicity_score: float,
    style: WalletStyle = WalletStyle.UNKNOWN,
    market_volatility_bps: float = 20.0
) -> float:
    """
    Penalizes signals from 'toxic' wallets or fast styles.
    """
    # Scale toxicity by market volatility hint
    base_penalty = toxicity_score * market_volatility_bps * 0.5

    multiplier = 1.0
    if style == WalletStyle.SCALPER_FAST:
        multiplier = 1.8
    elif style == WalletStyle.ILLIQUIDITY_HUNTER:
        multiplier = 2.5
    elif style == WalletStyle.SWING_TREND:
        multiplier = 0.7
    elif style == WalletStyle.MEAN_REVERSION:
        multiplier = 1.2

    return clamp(base_penalty * multiplier, 0.0, 30.0)


def compute_delay_cost(age_ms: int, volatility_bps_per_sec: float = 0.2) -> float:
    """
    Estimates the cost of delay due to price movement.
    """
    age_sec = max(0, age_ms / 1000.0)
    return age_sec * volatility_bps_per_sec


def compute_funding_penalty(side: str, funding_rate: float, expected_hold_hours: float = 8.0) -> float:
    """
    Estimates funding cost in bps for the expected hold period.
    """
    direction = 1.0 if side.lower() == "long" else -1.0
    cost_bps = direction * funding_rate * expected_hold_hours * 10000.0
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
    0 = impossible to replicate, 100 = perfect replication likely.
    """
    if edge_remaining_bps <= 0:
        return 0.0

    # 30% weight on how much edge we have above minimum
    edge_buffer = clamp((edge_remaining_bps - min_edge_required_bps) / 20.0, 0.0, 1.0)

    # 30% weight on freshness
    # 20% weight on consistency
    # 20% weight on liquidity

    score = (
        0.3 * edge_buffer * 100.0 +
        0.3 * freshness_factor * 100.0 +
        0.2 * clamp(consistency_factor, 0.0, 1.2) * 83.33333333333333 +
        0.2 * liquidity_score
    )
    return clamp(score, 0.0, 100.0)
