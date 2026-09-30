"""l2Book -> orderbook features: liquidity_score, spread_bps, microprice,
depth_imbalance, data_quality. Uses the Hyperliquid l2Book shape
{"levels": [bids, asks]} with px/sz entries. No network, deterministic.
"""

from hyper_smart_observer.market_signals.orderbook_features import compute_orderbook_features

L2 = {
    "levels": [
        [{"px": "100.0", "sz": "5"}, {"px": "99.5", "sz": "10"}],
        [{"px": "100.5", "sz": "5"}, {"px": "101.0", "sz": "10"}],
    ]
}


def test_l2book_features_are_computed_from_book():
    f = compute_orderbook_features("btc", L2, min_depth_usdc=10_000.0)
    assert f.coin == "BTC"
    assert f.best_bid == 100.0 and f.best_ask == 100.5
    assert f.spread_bps is not None and abs(f.spread_bps - 49.875) < 0.2
    assert f.microprice is not None and abs(f.microprice - 100.25) < 0.01
    assert f.depth_imbalance is not None and f.depth_imbalance < 0  # ask-heavy
    assert 0.0 < f.liquidity_score < 100.0
    assert abs(f.liquidity_score - 30.075) < 0.5
    assert f.data_quality == "OK"
    assert f.levels_per_side == 2


def test_l2book_liquidity_score_capped_for_deep_book():
    deep = {"levels": [[{"px": "100.0", "sz": "1000"}], [{"px": "100.5", "sz": "1000"}]]}
    f = compute_orderbook_features("BTC", deep, min_depth_usdc=10_000.0)
    assert f.liquidity_score == 100.0


def test_l2book_missing_side_flags_quality():
    one_sided = {"levels": [[{"px": "100.0", "sz": "5"}], []]}
    f = compute_orderbook_features("BTC", one_sided)
    assert f.best_ask is None
    assert f.data_quality == "MISSING_BOOK_SIDE"
    assert f.spread_bps is None
