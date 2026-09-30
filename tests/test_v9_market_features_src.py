from __future__ import annotations

import json

from hl_observer.features import (
    build_market_feature_vector,
    compute_orderbook_features,
    compute_volatility_context,
    derive_market_mid,
)


def _book() -> dict:
    return {
        "levels": [
            [{"px": "100.0", "sz": "8"}, {"px": "99.5", "sz": "12"}],
            [{"px": "100.5", "sz": "6"}, {"px": "101.0", "sz": "10"}],
        ]
    }


def test_v9_market_mid_has_explicit_source_and_missing_is_stale() -> None:
    from_book = derive_market_mid("btc", best_bid=100, best_ask=101)
    from_mids = derive_market_mid("btc", all_mids={"BTC": "100.25"})
    fallback = derive_market_mid("btc", last_trade_price="100.1")
    missing = derive_market_mid("btc")

    assert from_book.mid == 100.5
    assert from_book.mid_source == "MID_FROM_BOOK"
    assert from_book.source_endpoint == "l2Book"
    assert from_mids.mid == 100.25
    assert from_mids.mid_source == "MID_FROM_ALL_MIDS"
    assert fallback.data_quality == "DEGRADED"
    assert missing.mid is None
    assert missing.is_stale is True


def test_v9_orderbook_features_compute_spread_depth_microprice() -> None:
    features = compute_orderbook_features("btc", _book(), min_depth_usdc=5_000)

    assert features.coin == "BTC"
    assert features.best_bid == 100.0
    assert features.best_ask == 100.5
    assert round(features.spread_bps or 0, 3) == 49.875
    assert features.bid_depth_usdc == 1994.0
    assert features.ask_depth_usdc == 1613.0
    assert features.microprice is not None
    assert features.depth_imbalance is not None
    assert features.liquidity_score > 70
    assert features.data_quality == "OK"


def test_v9_volatility_context_uses_real_candles_without_fabrication() -> None:
    volatility = compute_volatility_context(
        [
            {"c": "100", "h": "101", "l": "99", "T": "1800000000000"},
            {"c": "101", "h": "102", "l": "100", "T": "1800000060000"},
            {"c": "104", "h": "105", "l": "99", "T": "1800000120000"},
        ]
    )

    assert volatility.samples == 3
    assert volatility.data_quality == "OK"
    assert volatility.range_bps is not None and volatility.range_bps > 0
    assert volatility.atr_bps is not None and volatility.atr_bps > 0
    assert volatility.source_ts_ms == 1_800_000_120_000

    missing = compute_volatility_context(None)
    assert missing.data_quality == "MISSING"
    assert missing.samples == 0


def test_v9_market_feature_vector_is_tradeable_when_market_is_clean() -> None:
    vector = build_market_feature_vector(
        timestamp_ms=1_800_000_200_000,
        source_ts_ms=1_800_000_199_900,
        coin="btc",
        l2_book=_book(),
        all_mids={"BTC": "100.25"},
        candles=[
            {"c": "100", "h": "100.5", "l": "99.8", "T": "1800000000000"},
            {"c": "100.1", "h": "100.6", "l": "99.9", "T": "1800000060000"},
            {"c": "100.2", "h": "100.7", "l": "100.0", "T": "1800000120000"},
        ],
    )

    assert vector.coin == "BTC"
    assert vector.quality_mode == "TRADEABLE"
    assert vector.quality_reasons == ("MARKET_FEATURES_OK",)
    assert vector.current_mid == 100.25
    assert vector.feature_hash.startswith("feat:")
    assert json.loads(vector.bid_levels_json)[0] == {"px": 100.0, "sz": 8.0}
    assert vector.to_row()["quality_reasons"] == "MARKET_FEATURES_OK"


def test_v9_market_feature_vector_blocks_stale_wide_and_thin_markets() -> None:
    thin_wide = {"levels": [[{"px": "90", "sz": "0.01"}], [{"px": "110", "sz": "0.01"}]]}

    vector = build_market_feature_vector(
        timestamp_ms=1,
        coin="BAD",
        l2_book=thin_wide,
        is_stale=True,
        max_spread_bps=50,
        min_liquidity_score=30,
    )

    assert vector.quality_mode == "NO_TRADE"
    assert "MARKET_DATA_STALE" in vector.quality_reasons
    assert "SPREAD_TOO_WIDE" in vector.quality_reasons
    assert "LIQUIDITY_TOO_LOW" in vector.quality_reasons
    assert vector.min_edge_bps_addon > 0
