"""Kelly Criterion position sizing — inspired by Polyphemus (36K-line bot).

The viral Polymarket bots use Kelly Criterion to size positions optimally.
This module implements a fractional Kelly (half-Kelly by default) for paper
simulation only.  No real orders, no real money.

References:
- Polyphemus (chudi.dev) uses full Kelly with confidence scaling
- Academic consensus: half-Kelly is safer in practice (lower variance)

SAFETY: simulation paper uniquement.  Aucun ordre réel.
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.copying.realtime_magic_score import clamp


@dataclass(frozen=True, slots=True)
class KellySizingConfig:
    """Configuration for Kelly Criterion sizing."""

    # Fraction of full Kelly to use (0.5 = half-Kelly, safer)
    kelly_fraction: float = 0.5

    # Minimum win probability to even consider a position
    min_win_probability: float = 0.52

    # Starting equity for paper simulation
    starting_equity_usdt: float = 1000.0

    # Absolute min/max per position
    min_position_usdt: float = 5.0
    max_position_usdt: float = 50.0

    # Max total exposure (all open positions)
    max_total_exposure_usdt: float = 200.0

    # Max single position as fraction of equity
    max_position_fraction: float = 0.05

    # Confidence scaling: high confidence leaders get full Kelly,
    # low confidence gets reduced
    confidence_scaling: bool = True


@dataclass(frozen=True, slots=True)
class KellySizingResult:
    """Output of Kelly sizing calculation."""

    position_size_usdt: float
    kelly_fraction_used: float
    full_kelly_fraction: float
    win_probability: float
    win_loss_ratio: float
    edge_quality: str  # "HIGH", "MEDIUM", "LOW", "REJECT"
    warnings: tuple[str, ...]


def kelly_criterion_size(
    *,
    edge_remaining_bps: float,
    leader_score: float,
    consensus_wallets: int,
    win_rate_estimate: float | None = None,
    current_open_exposure_usdt: float = 0.0,
    leader_notional_usdt: float = 0.0,
    config: KellySizingConfig | None = None,
) -> KellySizingResult:
    """Compute position size using Kelly Criterion.

    The key insight from the viral bots: size proportionally to edge,
    not uniformly.  Strong signals get bigger positions, weak signals
    get tiny positions or rejection.

    Win probability is estimated from:
    - Leader's historical win rate (if available)
    - Edge remaining (higher edge → higher implied win prob)
    - Leader score (proxy for consistency)
    - Consensus (multi-wallet confirmation boosts confidence)

    PAPER SIMULATION ONLY.
    """
    cfg = config or KellySizingConfig()
    warnings: list[str] = []

    # --- Estimate win probability ---
    consensus_boost = min(0.03, max(0, consensus_wallets - 1) * 0.01)

    if win_rate_estimate is not None and 0.0 < win_rate_estimate <= 1.0:
        # Explicit win rate: trust it, apply leader quality as small adjustment
        # leader_score/100 scales the win rate (e.g. 95 → 0.95 multiplier)
        leader_quality_factor = clamp(leader_score / 100.0, 0.7, 1.0)
        win_prob = clamp(
            win_rate_estimate * leader_quality_factor + consensus_boost,
            0.45,
            0.72,
        )
    else:
        # Derive from edge: edge_remaining_bps maps to win probability
        # 8 bps edge → ~52% win prob, 30 bps → ~58%, 50+ bps → ~62%
        base_win_prob = clamp(0.50 + edge_remaining_bps / 1000.0, 0.48, 0.70)
        leader_quality_factor = clamp(leader_score / 100.0, 0.5, 1.0)
        win_prob = clamp(
            base_win_prob * leader_quality_factor + consensus_boost,
            0.45,
            0.72,
        )

    if win_prob < cfg.min_win_probability:
        return KellySizingResult(
            position_size_usdt=0.0,
            kelly_fraction_used=0.0,
            full_kelly_fraction=0.0,
            win_probability=round(win_prob, 4),
            win_loss_ratio=0.0,
            edge_quality="REJECT",
            warnings=("WIN_PROBABILITY_TOO_LOW",),
        )

    # --- Win/Loss ratio from edge ---
    # Assume average win = edge_remaining_bps * win_multiplier
    # Assume average loss = edge_remaining_bps * loss_multiplier
    # For copy trading, wins and losses are roughly symmetric
    # but winners tend to be slightly larger (from leader's skill)
    avg_win_bps = max(1.0, edge_remaining_bps * 1.5)
    avg_loss_bps = max(1.0, edge_remaining_bps * 1.0)
    win_loss_ratio = avg_win_bps / avg_loss_bps

    # --- Kelly formula: f* = (p * b - q) / b ---
    # p = win probability, q = 1 - p, b = win/loss ratio
    q = 1.0 - win_prob
    full_kelly = (win_prob * win_loss_ratio - q) / win_loss_ratio

    if full_kelly <= 0:
        return KellySizingResult(
            position_size_usdt=0.0,
            kelly_fraction_used=0.0,
            full_kelly_fraction=round(full_kelly, 6),
            win_probability=round(win_prob, 4),
            win_loss_ratio=round(win_loss_ratio, 4),
            edge_quality="REJECT",
            warnings=("KELLY_NEGATIVE_NO_EDGE",),
        )

    # --- Apply fractional Kelly ---
    kelly_used = full_kelly * cfg.kelly_fraction

    # Confidence scaling: reduce for low-score leaders
    if cfg.confidence_scaling:
        confidence = clamp(leader_score / 80.0, 0.3, 1.0)
        kelly_used *= confidence
        if confidence < 0.6:
            warnings.append("LOW_CONFIDENCE_SCALING")

    # --- Convert to position size ---
    position_fraction = clamp(kelly_used, 0.0, cfg.max_position_fraction)
    target_usdt = cfg.starting_equity_usdt * position_fraction

    # Cap by leader's notional (don't copy bigger than leader)
    if leader_notional_usdt > 0:
        target_usdt = min(target_usdt, leader_notional_usdt)

    # Cap by absolute limits
    target_usdt = clamp(target_usdt, cfg.min_position_usdt, cfg.max_position_usdt)

    # Cap by remaining exposure
    remaining = max(0.0, cfg.max_total_exposure_usdt - current_open_exposure_usdt)
    if remaining <= 0:
        return KellySizingResult(
            position_size_usdt=0.0,
            kelly_fraction_used=round(kelly_used, 6),
            full_kelly_fraction=round(full_kelly, 6),
            win_probability=round(win_prob, 4),
            win_loss_ratio=round(win_loss_ratio, 4),
            edge_quality="REJECT",
            warnings=("MAX_TOTAL_EXPOSURE_CAP_ACTIVE",),
        )

    if target_usdt > remaining:
        target_usdt = remaining
        warnings.append("POSITION_SIZE_CAPPED_BY_TOTAL_EXPOSURE")

    if target_usdt < cfg.min_position_usdt:
        return KellySizingResult(
            position_size_usdt=0.0,
            kelly_fraction_used=round(kelly_used, 6),
            full_kelly_fraction=round(full_kelly, 6),
            win_probability=round(win_prob, 4),
            win_loss_ratio=round(win_loss_ratio, 4),
            edge_quality="REJECT",
            warnings=(*warnings, "POSITION_SIZE_BELOW_MINIMUM"),
        )

    # --- Classify edge quality ---
    if edge_remaining_bps >= 25 and win_prob >= 0.58:
        edge_quality = "HIGH"
    elif edge_remaining_bps >= 12 and win_prob >= 0.54:
        edge_quality = "MEDIUM"
    else:
        edge_quality = "LOW"

    return KellySizingResult(
        position_size_usdt=round(target_usdt, 2),
        kelly_fraction_used=round(kelly_used, 6),
        full_kelly_fraction=round(full_kelly, 6),
        win_probability=round(win_prob, 4),
        win_loss_ratio=round(win_loss_ratio, 4),
        edge_quality=edge_quality,
        warnings=tuple(warnings),
    )
