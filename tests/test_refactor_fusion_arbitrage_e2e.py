from hl_observer.arbitrage import (
    OrderBookSnapshot,
    compute_cross_exchange_spread,
    normalize_symbol,
    scan_hyperliquid_cex_spread,
)


def test_arbitrage_e2e_builds_positive_paper_opportunity_after_costs() -> None:
    hl = OrderBookSnapshot("hyperliquid_fixture", "HYPE-PERP", bid=99.9, ask=100.0, bid_size=200_000, ask_size=200_000)
    cex = OrderBookSnapshot("cex_fixture", "HYPE-USDT", bid=101.4, ask=101.6, bid_size=200_000, ask_size=200_000)

    result = scan_hyperliquid_cex_spread(
        hyperliquid_book=hl,
        cex_book=cex,
        fee_bps=6,
        slippage_bps=4,
        latency_penalty_bps=2,
        funding_rate=0,
    )

    assert result.decision == "ACCEPT_PAPER_ARBITRAGE"
    assert result.spread.net_edge_bps > 0
    assert result.paper_opportunity.accepted is True
    assert result.risk_decision.allow_new_entries is True
    assert result.real_execution is False


def test_arbitrage_e2e_rejects_missing_depth_or_bad_costs() -> None:
    hl = OrderBookSnapshot("hyperliquid_fixture", "HYPE-PERP", bid=99.9, ask=100.0, bid_size=1, ask_size=1)
    cex = OrderBookSnapshot("cex_fixture", "HYPE-USDT", bid=100.05, ask=100.1, bid_size=1, ask_size=1)

    result = scan_hyperliquid_cex_spread(hyperliquid_book=hl, cex_book=cex)

    assert result.decision == "NO_TRADE"
    assert result.paper_opportunity.accepted is False
    assert result.reason_codes
    assert result.real_execution is False


def test_symbol_normalization_and_spread_formula() -> None:
    assert normalize_symbol("HYPE-PERP") == "HYPE"
    spread = compute_cross_exchange_spread(
        long_book=OrderBookSnapshot("hl", "BTC-PERP", bid=100, ask=101, bid_size=100_000, ask_size=100_000),
        short_book=OrderBookSnapshot("cex", "BTC-USDT", bid=104, ask=105, bid_size=100_000, ask_size=100_000),
        fee_bps=5,
        slippage_bps=4,
        latency_penalty_bps=1,
    )
    assert spread.accepted is True
    assert spread.net_edge_bps > 0
