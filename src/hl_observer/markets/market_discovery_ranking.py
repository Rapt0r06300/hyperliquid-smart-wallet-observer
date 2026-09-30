"""V14 #172 — Market discovery ranked by VOLUME / LIQUIDITY (prioritise liquid markets).

Inspired by Polymarket/agents `get-all-markets --sort-by volume`. Pure ranking: takes
read-only market stats and returns a liquidity-first shortlist, excluding markets below
volume/liquidity floors (illiquid = expensive to copy). No network here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class MarketStat:
    coin: str
    volume_usd: float
    liquidity_score: float = 0.0   # 0..1 (our internal liquidity proxy)
    spread_bps: float = 0.0


@dataclass(frozen=True, slots=True)
class RankedMarket:
    coin: str
    rank: int
    volume_usd: float
    liquidity_score: float
    spread_bps: float


@dataclass(frozen=True, slots=True)
class MarketRanking:
    shortlist: tuple[RankedMarket, ...]
    excluded: tuple[tuple[str, str], ...]   # (coin, reason)
    considered: int


def rank_markets_by_liquidity(
    stats: Sequence[MarketStat],
    *,
    min_volume_usd: float = 50_000.0,
    min_liquidity_score: float = 0.22,
    max_spread_bps: float = 800.0,
    top_n: int = 80,
) -> MarketRanking:
    """Liquidity-first shortlist. Excludes illiquid / too-wide markets with a reason."""
    kept: list[MarketStat] = []
    excluded: list[tuple[str, str]] = []
    for s in stats:
        coin = str(s.coin or "").upper()
        if float(s.volume_usd) < min_volume_usd:
            excluded.append((coin, "VOLUME_TOO_LOW"))
            continue
        if float(s.liquidity_score) < min_liquidity_score:
            excluded.append((coin, "LIQUIDITY_TOO_LOW"))
            continue
        if float(s.spread_bps) > max_spread_bps:
            excluded.append((coin, "SPREAD_TOO_WIDE"))
            continue
        kept.append(s)
    # Sort by volume desc, then liquidity desc, then spread asc (tighter first).
    kept.sort(key=lambda s: (-float(s.volume_usd), -float(s.liquidity_score), float(s.spread_bps)))
    shortlist = tuple(
        RankedMarket(str(s.coin).upper(), i + 1, float(s.volume_usd), float(s.liquidity_score), float(s.spread_bps))
        for i, s in enumerate(kept[: max(0, top_n)])
    )
    return MarketRanking(shortlist=shortlist, excluded=tuple(excluded), considered=len(stats))


__all__ = ["MarketStat", "RankedMarket", "MarketRanking", "rank_markets_by_liquidity"]
