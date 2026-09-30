from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.arbitrage.orderbook_snapshot import OrderBookSnapshot


@dataclass(frozen=True, slots=True)
class CrossExchangeSpread:
    accepted: bool
    coin: str
    long_source: str
    short_source: str
    long_price: float
    short_price: float
    gross_spread_bps: float
    total_cost_bps: float
    net_edge_bps: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    paper_only: bool = True
    real_execution: bool = False


def compute_cross_exchange_spread(
    *,
    long_book: OrderBookSnapshot,
    short_book: OrderBookSnapshot,
    fee_bps: float = 6.0,
    slippage_bps: float = 4.0,
    latency_penalty_bps: float = 2.0,
    min_depth_score: float = 0.20,
    min_net_edge_bps: float = 8.0,
) -> CrossExchangeSpread:
    """Compute the long-ask to short-bid paper spread after costs."""

    reasons: list[str] = []
    if long_book.coin != short_book.coin:
        reasons.append("ARBITRAGE_SYMBOL_MISMATCH")
    if long_book.source == short_book.source:
        reasons.append("ARBITRAGE_REQUIRES_TWO_SOURCES")
    if long_book.ask <= 0 or short_book.bid <= 0:
        reasons.append("ARBITRAGE_BOOK_PRICE_INVALID")
    if min(long_book.depth_score, short_book.depth_score) < min_depth_score:
        reasons.append("ARBITRAGE_DEPTH_TOO_LOW")
    if reasons:
        return CrossExchangeSpread(
            accepted=False,
            coin=long_book.coin,
            long_source=long_book.source,
            short_source=short_book.source,
            long_price=long_book.ask,
            short_price=short_book.bid,
            gross_spread_bps=0.0,
            total_cost_bps=0.0,
            net_edge_bps=0.0,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    gross = (short_book.bid / long_book.ask - 1.0) * 10_000.0
    costs = max(0.0, fee_bps) + max(0.0, slippage_bps) + max(0.0, latency_penalty_bps)
    net = gross - costs
    if net < min_net_edge_bps:
        reasons.append("ARBITRAGE_NET_EDGE_TOO_LOW")
    return CrossExchangeSpread(
        accepted=not reasons,
        coin=long_book.coin,
        long_source=long_book.source,
        short_source=short_book.source,
        long_price=round(long_book.ask, 8),
        short_price=round(short_book.bid, 8),
        gross_spread_bps=round(gross, 8),
        total_cost_bps=round(costs, 8),
        net_edge_bps=round(net, 8),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


__all__ = ["CrossExchangeSpread", "compute_cross_exchange_spread"]
