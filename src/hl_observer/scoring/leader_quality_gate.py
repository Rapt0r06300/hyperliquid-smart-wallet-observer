"""Historical leader prefilter using verified closed cycles and replay costs.

This is a candidate-quality heuristic, not OOS/forward evidence or a profitability
certificate. Historical selection must be separated from later paper evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from hl_observer.backtest.ledger_replay_v9 import ReplayConfig


@dataclass(frozen=True, slots=True)
class LeaderQualityConfig:
    min_round_trips: int = 20
    min_winrate: float = 0.60
    min_mean_move_bps: float = 12.0        # minimum gross move; net edge is checked separately
    round_trip_cost_bps: float = ReplayConfig().round_trip_cost_bps
    min_net_edge_lcb_bps: float = 0.0
    max_one_trade_share: float = 0.60      # un seul trade ne doit pas porter tout le gain


@dataclass(frozen=True, slots=True)
class LeaderQuality:
    wallet: str
    round_trips: int
    winrate: float                         # proportion of cycles positive after configured costs
    mean_move_bps: float
    net_edge_bps: float                    # mean_move - cost
    net_edge_lcb_bps: float | None         # conservative lower bound; not an OOS certificate
    one_trade_share: float
    qualified: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def assess_leader_quality(
    wallet: str,
    moves_bps: list[float],
    *,
    config: LeaderQualityConfig | None = None,
) -> LeaderQuality:
    cfg = config or LeaderQualityConfig()
    n = len(moves_bps)
    if n == 0:
        return LeaderQuality(wallet, 0, 0.0, 0.0, -cfg.round_trip_cost_bps, None, 0.0, False, ("NO_HISTORY",))
    if any(isinstance(move, bool) or not isinstance(move, (int, float)) for move in moves_bps):
        return LeaderQuality(wallet, n, 0.0, 0.0, -cfg.round_trip_cost_bps, None, 0.0, False, ("INVALID_MOVE_SAMPLE",))
    try:
        moves = [float(move) for move in moves_bps]
    except (OverflowError, ValueError):
        return LeaderQuality(wallet, n, 0.0, 0.0, -cfg.round_trip_cost_bps, None, 0.0, False, ("INVALID_MOVE_SAMPLE",))
    if any(not math.isfinite(move) for move in moves):
        return LeaderQuality(wallet, n, 0.0, 0.0, -cfg.round_trip_cost_bps, None, 0.0, False, ("INVALID_MOVE_SAMPLE",))
    net_moves = [move - cfg.round_trip_cost_bps for move in moves]
    wins = sum(1 for move in net_moves if move > 0)
    winrate = wins / n
    mean_move = sum(moves) / n
    net_edge = mean_move - cfg.round_trip_cost_bps
    sample_variance = sum((move - mean_move) ** 2 for move in moves) / (n - 1) if n > 1 else 0.0
    net_edge_lcb = net_edge - 1.96 * math.sqrt(sample_variance / n)
    gains = [move for move in net_moves if move > 0]
    total_gain = sum(gains)
    one_trade_share = (max(gains) / total_gain) if total_gain > 0 else 0.0

    reasons: list[str] = []
    if n < cfg.min_round_trips:
        reasons.append(f"TOO_FEW_TRIPS_{n}<{cfg.min_round_trips}")
    if winrate < cfg.min_winrate:
        reasons.append(f"WINRATE_{winrate:.2f}<{cfg.min_winrate:.2f}")
    if mean_move < cfg.min_mean_move_bps:
        reasons.append(f"MEAN_MOVE_{mean_move:.1f}<{cfg.min_mean_move_bps:.1f}bps")
    if net_edge <= 0:
        reasons.append(f"NON_POSITIVE_NET_EDGE_{net_edge:.1f}bps")
    if net_edge_lcb <= cfg.min_net_edge_lcb_bps:
        reasons.append(f"NET_EDGE_LCB_{net_edge_lcb:.1f}<={cfg.min_net_edge_lcb_bps:.1f}bps")
    if one_trade_share > cfg.max_one_trade_share:
        reasons.append("ONE_BIG_WIN_RISK")

    qualified = not reasons
    if qualified:
        reasons.append("SMART_MONEY")
    return LeaderQuality(
        wallet=wallet,
        round_trips=n,
        winrate=round(winrate, 4),
        mean_move_bps=round(mean_move, 4),
        net_edge_bps=round(net_edge, 4),
        net_edge_lcb_bps=round(net_edge_lcb, 4),
        one_trade_share=round(one_trade_share, 4),
        qualified=qualified,
        reasons=tuple(reasons),
    )


def select_smart_money(
    wallet_moves: dict[str, list[float]],
    *,
    config: LeaderQualityConfig | None = None,
) -> list[LeaderQuality]:
    """Retourne les leaders QUALIFIÉS uniquement, classés par edge net décroissant."""
    assessed = [assess_leader_quality(w, m, config=config) for w, m in wallet_moves.items()]
    qualified = [a for a in assessed if a.qualified]
    qualified.sort(key=lambda a: -a.net_edge_bps)
    return qualified


__all__ = ["LeaderQualityConfig", "LeaderQuality", "assess_leader_quality", "select_smart_money"]
