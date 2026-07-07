"""Opportunity power-ranking with per-coin diversification (V9 — signal fort).

The scan surfaces many fresh candidates across dozens of coins. This module
turns each candidate into a single **power score** by blending the V9 quality
signals already implemented elsewhere — net edge (after costs), freshness decay,
multi-wallet consensus, liquidity, directional trend alignment, and smart-money
leader quality — then ranks them so the bot copies the *strongest* opportunities
first instead of re-trading whatever fires most often (e.g. ETH).

Crucially it also **diversifies**: a per-coin cap stops a single high-frequency
coin from taking every position slot, which was the measured cause of the
"96% ETH" concentration (non-ETH candidates were locked out by full slots).

Pure, deterministic, paper-only. A high power score is a *research ranking*, not
an order, not a recommendation, not a promise of profit. Candidates that fail a
hard floor (no net edge, stale, illiquid) score 0 and are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.freshness.signal_decay import freshness_factor_calibrated


@dataclass(frozen=True, slots=True)
class RankerConfig:
    min_net_edge_bps: float = 8.0       # hard floor: below this, no opportunity
    min_liquidity_score: float = 0.30   # hard floor: too illiquid -> drop
    max_signal_age_ms: int = 30_000     # hard floor: older -> stale -> drop
    max_per_coin: int = 2               # diversification: at most N kept per coin
    # weights of the blended power score (sum is normalised internally).
    # Consensus (independent wallets agreeing) is weighted high on purpose: a
    # multi-wallet signal is the strongest "proof" of a real move (user request).
    w_edge: float = 0.34
    w_consensus: float = 0.28
    w_liquidity: float = 0.13
    w_trend: float = 0.10
    w_leader: float = 0.15


@dataclass(frozen=True, slots=True)
class OpportunityInput:
    coin: str
    side: str
    net_edge_bps: float
    signal_age_ms: int
    consensus_wallets: int = 1
    liquidity_score: float = 0.5
    directional_bias_bps: float = 0.0     # + aligned with trend, - against
    leader_winrate: float | None = None   # 0..1 (smart-money history), None = unknown


@dataclass(frozen=True, slots=True)
class RankedOpportunity:
    coin: str
    side: str
    power_score: float          # 0..100
    net_edge_bps: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def power_score(opp: OpportunityInput, config: RankerConfig | None = None) -> float:
    """Blended 0..100 power score; 0 means it failed a hard floor (drop it)."""
    cfg = config or RankerConfig()
    # hard floors
    if opp.net_edge_bps < cfg.min_net_edge_bps:
        return 0.0
    if opp.liquidity_score < cfg.min_liquidity_score:
        return 0.0
    if opp.signal_age_ms > cfg.max_signal_age_ms:
        return 0.0

    # normalised components in [0,1]
    edge_c = _clamp(opp.net_edge_bps / 40.0, 0.0, 1.0)               # 40 bps net = full
    consensus_c = _clamp((opp.consensus_wallets - 1) / 3.0, 0.0, 1.0)  # 4+ wallets = full
    liquidity_c = _clamp(opp.liquidity_score, 0.0, 1.0)
    freshness_c = freshness_factor_calibrated(opp.signal_age_ms, cfg.max_signal_age_ms)
    trend_c = _clamp(0.5 + opp.directional_bias_bps / 20.0, 0.0, 1.0)  # bias +-10bps -> 0..1
    leader_c = 0.5 if opp.leader_winrate is None else _clamp(opp.leader_winrate, 0.0, 1.0)

    wsum = cfg.w_edge + cfg.w_consensus + cfg.w_liquidity + cfg.w_trend + cfg.w_leader
    raw = (
        cfg.w_edge * edge_c
        + cfg.w_consensus * consensus_c
        + cfg.w_liquidity * liquidity_c
        + cfg.w_trend * trend_c
        + cfg.w_leader * leader_c
    ) / (wsum or 1.0)
    # fold freshness in multiplicatively (a stale-ish signal can't be top power)
    score = raw * freshness_c
    return round(_clamp(score, 0.0, 1.0) * 100.0, 4)


def rank_opportunities(
    candidates: list[OpportunityInput],
    config: RankerConfig | None = None,
    *,
    limit: int | None = None,
) -> list[RankedOpportunity]:
    """Score, drop floor-failures, sort by power desc, enforce per-coin cap."""
    cfg = config or RankerConfig()
    scored: list[RankedOpportunity] = []
    for c in candidates:
        s = power_score(c, cfg)
        if s <= 0.0:
            continue
        scored.append(RankedOpportunity(coin=str(c.coin or "").upper(), side=str(c.side or "").upper(),
                                        power_score=s, net_edge_bps=round(c.net_edge_bps, 4)))
    scored.sort(key=lambda r: -r.power_score)

    # diversification: cap how many of each coin survive
    per_coin: dict[str, int] = {}
    kept: list[RankedOpportunity] = []
    for r in scored:
        n = per_coin.get(r.coin, 0)
        if n >= cfg.max_per_coin:
            continue
        per_coin[r.coin] = n + 1
        kept.append(r)
        if limit is not None and len(kept) >= limit:
            break
    return kept


__all__ = [
    "RankerConfig",
    "OpportunityInput",
    "RankedOpportunity",
    "power_score",
    "rank_opportunities",
]
