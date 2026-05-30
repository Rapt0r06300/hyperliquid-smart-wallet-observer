from __future__ import annotations

import math
from hl_observer.hyperliquid.schemas import WalletStyle
from hl_observer.utils.math import clamp


def compute_freshness_factor(age_ms: int, half_life_ms: float = 3500.0, volatility_index: float = 1.0) -> float:
    """
    Calculates signal freshness using exponential decay.
    Volatility-adjusted: high volatility causes faster edge decay.
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
    Estimates a liquidity penalty in bps using a Square Root Market Impact model.
    A professional-grade estimate of slippage and market impact.
    """
    if depth_usdc <= 0:
        return 100.0

    if notional_usdc <= 0:
        return 0.0

    # Impact_bps = Intensity * sqrt(TradeSize / Depth)
    ratio = notional_usdc / max(1.0, depth_usdc)
    penalty = math.sqrt(ratio) * 40.0
    return clamp(penalty, 0.0, 100.0)


def compute_crowding_penalty(
    num_leaders: int,
    total_notional_usdc: float = 0.0,
    threshold_count: int = 3,
    threshold_notional: float = 50000.0
) -> float:
    """
    Penalizes signals if too many leaders or too much aggregate notional is moving.
    Crowding leads to alpha decay and liquidity exhaustion.
    """
    if num_leaders <= threshold_count and total_notional_usdc < threshold_notional:
        return 0.0

    # Count penalty: 4bps per additional leader
    count_penalty = max(0.0, (num_leaders - threshold_count) * 4.0)

    # Size penalty: 3bps per $100k of total leader volume
    size_penalty = (total_notional_usdc / 100000.0) * 3.0

    return clamp(count_penalty + size_penalty, 0.0, 50.0)


def compute_adverse_selection_penalty(
    toxicity_score: float,
    style: WalletStyle = WalletStyle.UNKNOWN,
    market_volatility_bps: float = 20.0
) -> float:
    """
    Penalizes signals likely to be 'informed flow' that is already front-run or
    subject to immediate mean reversion.
    """
    # Scale toxicity by volatility
    base_penalty = toxicity_score * market_volatility_bps * 0.6

    multipliers = {
        WalletStyle.SCALPER_FAST: 2.2,
        WalletStyle.ILLIQUIDITY_HUNTER: 3.5,
        WalletStyle.SWING_TREND: 0.5,
        WalletStyle.MEAN_REVERSION: 1.2,
        WalletStyle.UNKNOWN: 1.0
    }
    multiplier = multipliers.get(style, 1.0)
    return clamp(base_penalty * multiplier, 0.0, 45.0)


def compute_delay_cost(age_ms: int, volatility_bps_per_sec: float = 0.2) -> float:
    """
    Estimates the cost of delay due to expected price drift.
    """
    age_sec = max(0, age_ms / 1000.0)
    return age_sec * volatility_bps_per_sec


def compute_funding_penalty(side: str, funding_rate: float, expected_hold_hours: float = 8.0) -> float:
    """
    Estimates funding carry cost/gain in bps for the expected hold period.
    A negative value indicates a gain (receiving funding).
    """
    # Longs pay shorts when funding is positive.
    direction = 1.0 if side.lower() == "long" else -1.0

    # funding_rate is assumed to be hourly (e.g., 0.0001 = 1bp/hr)
    cost_bps = direction * funding_rate * expected_hold_hours * 10000.0
    return cost_bps


def compute_confirmation_bonus(
    num_leaders: int,
    cluster_consensus_score: float = 0.0,
    orderbook_imbalance: float = 0.0
) -> float:
    """
    Adds a 'conviction bonus' when signals are confirmed by multiple independent
    leaders or market microstructure signs.
    """
    # 5 bps per additional leader, capped at 20 bps
    leader_bonus = min(20.0, max(0.0, num_leaders - 1) * 5.0)

    # Bonus from cluster quality (0-100 score)
    cluster_bonus = clamp(cluster_consensus_score / 10.0, 0.0, 15.0)

    # Microstructure bonus (placeholder for imbalance analysis)
    imbalance_bonus = clamp(orderbook_imbalance * 10.0, 0.0, 5.0)

    return leader_bonus + cluster_bonus + imbalance_bonus


def compute_kelly_sizing(edge_bps: float, win_rate: float = 0.5) -> float:
    """
    Calculates a suggested position size based on the Kelly Criterion.
    """
    if edge_bps <= 0:
        return 0.0

    # Basic Kelly: f* = (p - q) / b (assuming b=1 odds)
    kelly_fraction = (2.0 * win_rate) - 1.0

    # Dampen sizing by edge strength to avoid over-leveraging on weak alpha
    strength_factor = clamp(edge_bps / 25.0, 0.2, 1.0)

    return clamp(kelly_fraction * strength_factor, 0.0, 1.0)


def compute_gain_assurance_score(
    edge_remaining_bps: float,
    min_edge_required_bps: float,
    freshness_factor: float,
    consistency_factor: float,
    liquidity_score: float,
) -> float:
    """
    Composite probability score (0-100) representing the likelihood that
    a follower can capture the residual edge.
    """
    if edge_remaining_bps <= 0:
        return 0.0

    # Alpha margin above threshold (35%)
    edge_buffer = clamp((edge_remaining_bps - min_edge_required_bps) / 25.0, 0.0, 1.0)

    # Freshness of information (30%)
    # Leader historical consistency (20%)
    # Microstructure execution liquidity (15%)

    score = (
        0.35 * edge_buffer * 100.0 +
        0.30 * freshness_factor * 100.0 +
        0.20 * clamp(consistency_factor, 0.0, 1.2) * 83.33 +
        0.15 * liquidity_score
    )
    return clamp(score, 0.0, 100.0)
