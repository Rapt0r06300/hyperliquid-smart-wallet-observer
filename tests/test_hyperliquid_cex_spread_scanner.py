from hl_observer.arbitrage.hyperliquid_cex_spread_scanner import scan_hyperliquid_cex_spread
from hl_observer.arbitrage.orderbook_snapshot import OrderBookSnapshot


def test_hyperliquid_cex_spread_scanner_accepts_best_direction_paper_only() -> None:
    result = scan_hyperliquid_cex_spread(
        hyperliquid_book=OrderBookSnapshot("hyperliquid", "SOL-PERP", bid=199, ask=200, bid_size=150_000, ask_size=150_000),
        cex_book=OrderBookSnapshot("cex", "SOL-USDT", bid=204, ask=205, bid_size=150_000, ask_size=150_000),
    )

    assert result.decision == "ACCEPT_PAPER_ARBITRAGE"
    assert result.spread.long_source == "hyperliquid"
    assert result.paper_opportunity.external_action is False
    assert result.real_execution is False


def test_hyperliquid_cex_spread_scanner_rejects_missing_second_leg_depth() -> None:
    result = scan_hyperliquid_cex_spread(
        hyperliquid_book=OrderBookSnapshot("hyperliquid", "SOL-PERP", bid=199, ask=200, bid_size=150_000, ask_size=150_000),
        cex_book=OrderBookSnapshot("cex", "SOL-USDT", bid=204, ask=205, bid_size=1, ask_size=1),
    )

    assert result.decision == "NO_TRADE"
    assert "ARBITRAGE_DEPTH_TOO_LOW" in result.reason_codes
