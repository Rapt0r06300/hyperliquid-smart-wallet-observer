"""volatility_context from candles: real metric when present, None/degraded when not."""

from __future__ import annotations

from hyper_smart_observer.market_signals.volatility import compute_volatility_context


def test_valid_candles_give_realized_volatility():
    candles = [
        {
            "c": str(100 + (i % 5) * 0.7),
            "h": str(101 + i * 0.1),
            "l": str(99 - i * 0.1),
            "T": 1_800_000_000_000 + i * 60_000,
        }
        for i in range(30)
    ]
    v = compute_volatility_context(candles)
    assert v.data_quality == "OK"
    assert v.realized_vol_bps is not None and v.realized_vol_bps >= 0.0
    assert v.range_bps is not None and v.range_bps >= 0.0
    assert v.atr_bps is not None and v.atr_bps >= 0.0
    assert v.source_ts == candles[-1]["T"]
    assert v.bucket in ("LOW", "NORMAL", "HIGH", "EXTREME")


def test_absent_candles_are_missing_not_invented():
    v = compute_volatility_context([])
    assert v.realized_vol_bps is None and v.data_quality == "MISSING"


def test_single_candle_is_degraded():
    v = compute_volatility_context([{"c": "100", "t": 123}])
    assert v.realized_vol_bps is None and v.data_quality == "DEGRADED"
    assert v.atr_bps is None
    assert v.source_ts == 123


def test_large_range_sets_extreme_bucket_without_inventing_values():
    candles = [
        {"c": "100", "h": "101", "l": "99", "T": 1},
        {"c": "120", "h": "160", "l": "80", "T": 2},
        {"c": "90", "h": "170", "l": "70", "T": 3},
    ]
    v = compute_volatility_context(candles)
    assert v.data_quality == "OK"
    assert v.bucket == "EXTREME"
    assert v.range_bps is not None and v.range_bps > 1_000
