from __future__ import annotations

from hl_observer.features.scan_features import build_scan_features
from hl_observer.features.scan_features_schema import (
    EXPECTED_SCAN_FEATURE_COLUMNS,
    validate_scan_feature_row,
)


def _prices(n: int = 80) -> list[float]:
    return [100.0 + index * 0.1 for index in range(n)]


def test_v12_scan_features_have_explicit_70_plus_schema_and_hash():
    features = build_scan_features(
        coin="HYPE",
        now_ms=1_700_000_010_000,
        fill_ts_ms=1_700_000_000_000,
        mid=110.0,
        leader_price=109.5,
        best_bid=109.95,
        best_ask=110.05,
        bid_depth_usdc=70_000,
        ask_depth_usdc=50_000,
        recent_prices=_prices(),
        recent_trades=[(110.0, 2.0), (110.1, -1.0), (110.2, 4.0)],
        volume_window_usdc=2_500_000,
        avg_volume_usdc=1_000_000,
        leader_notional_usdc=80_000,
        leader_score=91.0,
        consensus_wallets=4,
    )
    row = features.to_row()
    ok, reasons = validate_scan_feature_row(row)

    assert len(EXPECTED_SCAN_FEATURE_COLUMNS) >= 70
    assert len(row) >= 70
    assert ok, reasons
    assert row["feature_hash"].startswith("feat:")
    assert row["execution"] == "forbidden"
    assert row["read_only"] is True


def test_v12_scan_feature_hash_is_deterministic():
    kwargs = dict(
        coin="BTC",
        now_ms=1_700_000_010_000,
        fill_ts_ms=1_700_000_000_000,
        mid=100.0,
        best_bid=99.9,
        best_ask=100.1,
        bid_depth_usdc=30_000,
        ask_depth_usdc=30_000,
        recent_prices=_prices(),
    )
    assert build_scan_features(**kwargs).feature_hash == build_scan_features(**kwargs).feature_hash


def test_v12_scan_features_missing_data_stays_none_not_zero():
    features = build_scan_features(coin="PURR")
    row = features.to_row()
    ok, reasons = validate_scan_feature_row(row)

    assert ok, reasons
    assert row["quality"] == "BAD"
    assert row["mid"] is None
    assert row["spread_bps"] is None
    assert row["cvd"] is None
    assert row["ret_60"] is None
    assert row["vol_60"] is None
