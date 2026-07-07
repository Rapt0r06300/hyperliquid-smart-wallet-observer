from hl_observer.arbitrage.orderbook_snapshot import OrderBookSnapshot
from hl_observer.arbitrage.spread_formula import compute_cross_exchange_spread


def test_arbitrage_spread_formula_subtracts_costs() -> None:
    spread = compute_cross_exchange_spread(
        long_book=OrderBookSnapshot("hl", "HYPE-PERP", bid=99.9, ask=100.0, bid_size=100_000, ask_size=100_000),
        short_book=OrderBookSnapshot("cex", "HYPE-USDT", bid=101.0, ask=101.2, bid_size=100_000, ask_size=100_000),
        fee_bps=6,
        slippage_bps=4,
        latency_penalty_bps=2,
    )

    assert spread.accepted is True
    assert spread.gross_spread_bps == 100.0
    assert spread.total_cost_bps == 12.0
    assert spread.net_edge_bps == 88.0
