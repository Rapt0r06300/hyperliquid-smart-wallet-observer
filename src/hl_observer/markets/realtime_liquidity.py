"""Realtime liquidity score for the copy gate — market-based, not fill-based.

Root cause fixed here (2026-07-03): the realtime copy gate used
``max(0.2, min(1.0, fill_notional / 2500))`` as "liquidity_score". That is the
*size of the leader's fill*, not the liquidity of the market. A whale adding a
45 USDT clip on BTC produced 0.2 < 0.22 threshold → ``LIQUIDITY_TOO_LOW`` on
the deepest market of Hyperliquid (observed 1472 refusals on BTC alone in one
session), while a large fill on a thin exotic coin scored high. The gate was
effectively inverted.

This module scores the *market*:

1. If a fresh measured market liquidity score (0..1, e.g. from stored l2Book
   coin metrics) is provided, it dominates.
2. Otherwise a conservative static tier for well-known deep Hyperliquid
   markets is used. This is not fabricated data: it encodes the stable,
   publicly observable fact that BTC/ETH/SOL/... books are deep. It is a
   fallback, clearly labelled, never presented as a live measurement.
3. Unknown coins keep the previous notional proxy, WITHOUT the artificial
   0.2 floor (the floor parked every small fill just under the 0.22 gate).

Pure function, no I/O, paper/simulation only. Nothing here places orders.
"""

from __future__ import annotations

# Deep books on Hyperliquid — top-of-leaderboard perp markets. Conservative
# static fallback; a measured score always wins when available.
DEEP_LIQUIDITY_COINS: frozenset[str] = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "HYPE",
        "XRP",
        "DOGE",
        "BNB",
        "AVAX",
        "LINK",
        "ADA",
        "SUI",
        "LTC",
        "BCH",
        "ARB",
        "OP",
        "APT",
        "ATOM",
        "NEAR",
        "DOT",
        "WLD",
        "AAVE",
        "UNI",
        "ENA",
        "TON",
        "TAO",
        "INJ",
        "TIA",
        "SEI",
        "FIL",
        "JUP",
    }
)

# Liquid but thinner mid markets (rest of the routinely scanned universe).
MID_LIQUIDITY_COINS: frozenset[str] = frozenset(
    {
        "CRV",
        "ONDO",
        "PENGU",
        "FARTCOIN",
        "WIF",
        "KPEPE",
        "PEPE",
        "TRUMP",
        "ETC",
        "PAXG",
        "ALGO",
        "COMP",
        "DASH",
        "DYDX",
        "EIGEN",
        "BLUR",
        "CAKE",
        "CELO",
        "CFX",
        "APE",
        "AXS",
        "BERA",
        "BIO",
        "BOME",
        "BRETT",
        "BSV",
        "DYM",
        "AERO",
        "AIXBT",
        "ALT",
        "ANIME",
        "AR",
        "ASTER",
        "PUMP",
        "SPX",
        "ZEC",
        "PYTH",
        "FET",
        "XPL",
        "LIT",
    }
)

DEEP_TIER_SCORE: float = 0.92
MID_TIER_SCORE: float = 0.65
NOTIONAL_FULL_SCALE_USDC: float = 2_500.0


def notional_proxy_score(
    notional_usdc: float,
    *,
    full_scale_usdc: float = NOTIONAL_FULL_SCALE_USDC,
) -> float:
    """Legacy proxy: fill/cluster notional scaled to 0..1. No artificial floor."""
    if full_scale_usdc <= 0:
        return 0.0
    value = max(0.0, float(notional_usdc or 0.0)) / float(full_scale_usdc)
    return max(0.0, min(1.0, value))


def static_tier_score(coin: str) -> float | None:
    """Conservative static market tier, or None for unknown coins."""
    symbol = str(coin or "").strip().upper()
    if not symbol:
        return None
    # Hyperliquid spot/exotic prefixes are never tiered here; upstream gates
    # (EXOTIC_MARKET_SKIPPED) already handle them and unknown stays unknown.
    if ":" in symbol or symbol.startswith("@"):
        return None
    if symbol in DEEP_LIQUIDITY_COINS:
        return DEEP_TIER_SCORE
    if symbol in MID_LIQUIDITY_COINS:
        return MID_TIER_SCORE
    return None


def resolve_realtime_liquidity_score(
    *,
    coin: str,
    leader_notional_usdc: float,
    cluster_notional_usdc: float,
    consensus_wallets: int,
    measured_market_score: float | None = None,
) -> float:
    """Market-based liquidity score in [0, 1] for the realtime copy gate.

    Priority: measured market score > static tier > notional proxy. The
    notional evidence can only ever *raise* the score of a tiered market
    (a large consensus burst is extra evidence), never sink a deep market
    because one copied fill was small.
    """
    basis = (
        float(cluster_notional_usdc or 0.0)
        if int(consensus_wallets or 0) >= 2
        else float(leader_notional_usdc or 0.0)
    )
    proxy = notional_proxy_score(basis)

    if measured_market_score is not None:
        try:
            measured = float(measured_market_score)
        except (TypeError, ValueError):
            measured = 0.0
        if measured > 0:
            return max(0.0, min(1.0, max(measured, proxy)))

    tier = static_tier_score(coin)
    if tier is not None:
        return max(tier, proxy)
    return proxy


__all__ = [
    "DEEP_LIQUIDITY_COINS",
    "DEEP_TIER_SCORE",
    "MID_LIQUIDITY_COINS",
    "MID_TIER_SCORE",
    "NOTIONAL_FULL_SCALE_USDC",
    "notional_proxy_score",
    "resolve_realtime_liquidity_score",
    "static_tier_score",
]
