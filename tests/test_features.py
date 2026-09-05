"""Tests des features de marché (propriétés)."""
from __future__ import annotations

from hl_observer.backtesting.features import atr, realized_vol, time_features


def test_realized_vol_higher_for_volatile_series():
    calm = [100.0, 100.1, 100.0, 100.1, 100.0, 100.1, 100.0]
    wild = [100.0, 105.0, 96.0, 108.0, 94.0, 110.0, 92.0]
    assert realized_vol(wild) > realized_vol(calm) >= 0.0


def test_atr_basic():
    highs = [10, 11, 12, 13]
    lows = [9, 9, 10, 11]
    closes = [9.5, 10.5, 11.5, 12.5]
    assert atr(highs, lows, closes, window=3) > 0.0


def test_atr_returns_zero_with_insufficient_history():
    assert atr([10], [9], [9.5]) == 0.0


def test_time_features_epoch():
    f = time_features(0)                 # 1970-01-01 00:00 UTC = jeudi (wday=3)
    assert f["hour"] == 0
    assert f["day_of_week"] == 3
    assert f["is_weekend"] == 0
    assert abs(f["hour_cos"] - 1.0) < 1e-9
