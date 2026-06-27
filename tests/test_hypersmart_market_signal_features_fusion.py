from __future__ import annotations

import csv
import json

from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps
from hyper_smart_observer.copy_mode.copy_models import EdgeInputs, NoTradeReason
from hyper_smart_observer.market_signals.exporter import (
    SCAN_FEATURE_COLUMNS,
    write_scan_features_export,
)
from hyper_smart_observer.market_signals.market_signal_features import (
    build_market_signal_features,
)
from hyper_smart_observer.market_signals.mid_stability import derive_market_mid
from hyper_smart_observer.market_signals.orderbook_features import compute_orderbook_features
from hyper_smart_observer.market_signals.volatility import compute_volatility_context


def _book():
    return {
        "coin": "BTC",
        "levels": [
            [
                {"px": "99", "sz": "10"},
                {"px": "98", "sz": "5"},
            ],
            [
                {"px": "101", "sz": "4"},
                {"px": "102", "sz": "6"},
            ],
        ],
    }


def test_market_mid_source_quality_fallback():
    book_mid = derive_market_mid("BTC", best_bid=99, best_ask=101)
    assert book_mid.mid == 100
    assert book_mid.mid_source == "MID_FROM_BOOK"
    assert book_mid.data_quality == "OK"

    all_mids = derive_market_mid("BTC", all_mids={"BTC": "100.5"})
    assert all_mids.mid == 100.5
    assert all_mids.mid_source == "MID_FROM_BOOK"
    assert all_mids.source_endpoint == "allMids"

    fallback = derive_market_mid("BTC", last_trade_price="100.25")
    assert fallback.mid == 100.25
    assert fallback.mid_source == "MID_FROM_LAST_TRADE_FALLBACK"
    assert fallback.data_quality == "DEGRADED"

    missing = derive_market_mid("BTC")
    assert missing.mid is None
    assert missing.mid_source == "MID_MISSING"
    assert missing.is_stale is True


def test_l2book_liquidity_score_and_depth_shape():
    features = compute_orderbook_features("BTC", _book(), min_depth_usdc=2_000)

    assert features.best_bid == 99
    assert features.best_ask == 101
    assert round(features.spread_bps or 0, 2) == 200.0
    assert features.bid_depth_usdc == 1480
    assert features.ask_depth_usdc == 1016
    assert features.liquidity_score == 100.0
    assert features.depth_imbalance is not None
    assert features.microprice is not None
    assert features.data_quality == "OK"


def test_market_signal_features_rich_export_schema():
    features = build_market_signal_features(
        timestamp_ms=1_800_000_000_000,
        source_ts=1_800_000_000_100,
        symbol="btc",
        wallet="0x" + "a" * 40,
        l2_book=_book(),
        all_mids={"BTC": "100"},
        leader_delta="OPEN_LONG",
        leader_reference_price=99.5,
        copy_degradation_bps=8.0,
        edge_remaining_bps=42.0,
        volatility_context=0.12,
        source_health="OK",
    )

    row = features.to_export_row()
    assert set(row) == set(SCAN_FEATURE_COLUMNS)
    assert row["symbol"] == "BTC"
    assert row["current_mid"] == 100
    assert row["mid_source"] == "MID_FROM_BOOK"
    assert row["mid_source_endpoint"] == "l2Book"
    assert row["bid_depth_usdc"] == 1480
    assert row["ask_depth_usdc"] == 1016
    assert row["l2_levels_per_side"] == 2
    assert json.loads(row["l2_bid_levels_json"])[0] == {"px": 99.0, "sz": 10.0}
    assert row["data_quality"] == "OK"
    assert row["volatility_realized_bps"] == 0.12
    assert row["volatility_data_quality"] == "LEGACY_NUMERIC"
    assert row["schema_version"] == "market_signal_features.v1"


def test_market_signal_features_export_real_volatility_context():
    volatility = compute_volatility_context(
        [
            {"c": "100", "h": "101", "l": "99", "T": "1800000000000"},
            {"c": "101", "h": "102", "l": "100", "T": "1800000060000"},
            {"c": "103", "h": "104", "l": "99", "T": "1800000120000"},
        ]
    )
    features = build_market_signal_features(
        timestamp_ms=1_800_000_200_000,
        source_ts=1_800_000_200_100,
        symbol="BTC",
        l2_book=_book(),
        all_mids={"BTC": "100"},
        volatility_context=volatility,
        source_health="OK",
    )

    row = features.to_export_row()
    assert row["volatility_context"] == volatility.realized_vol_bps
    assert row["volatility_range_bps"] == volatility.range_bps
    assert row["volatility_atr_bps"] == volatility.atr_bps
    assert row["volatility_bucket"] == volatility.bucket
    assert row["volatility_samples"] == volatility.samples
    assert row["volatility_data_quality"] == "OK"
    assert row["volatility_source_ts"] == 1_800_000_120_000


def test_scan_features_csv_json_export_per_run(tmp_path):
    feature = build_market_signal_features(
        timestamp_ms=1_800_000_000_000,
        source_ts=1_800_000_000_100,
        symbol="BTC",
        wallet="0x" + "b" * 40,
        l2_book=_book(),
        all_mids={"BTC": "100"},
        leader_delta="OPEN_LONG",
        leader_reference_price=99.5,
        copy_degradation_bps=8.0,
        edge_remaining_bps=42.0,
        volatility_context=0.12,
        source_health="OK",
    )

    result = write_scan_features_export([feature], tmp_path, run_id="scan:run/1")

    assert result.run_id == "scan_run_1"
    assert result.rows == 1
    assert result.json_path.exists()
    assert result.csv_path.exists()
    json_rows = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert json_rows[0]["symbol"] == "BTC"
    assert json_rows[0]["edge_remaining_bps"] == 42.0

    with result.csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["symbol"] == "BTC"
    assert list(rows[0]) == list(SCAN_FEATURE_COLUMNS)

    empty = write_scan_features_export([], tmp_path, run_id="empty")
    assert json.loads(empty.json_path.read_text(encoding="utf-8")) == []
    assert empty.csv_path.read_text(encoding="utf-8").splitlines() == [",".join(SCAN_FEATURE_COLUMNS)]


def test_edge_remaining_uses_spread_fee_slippage_latency_copy_degradation():
    edge, degradation, reasons = compute_edge_remaining_bps(
        EdgeInputs(
            leader_expected_edge_bps=20.0,
            delay_cost_bps=5.0,
            spread_bps=10.0,
            slippage_bps=4.0,
            fee_bps=3.0,
            adverse_selection_penalty_bps=6.0,
        ),
        min_required_bps=35.0,
        max_copy_degradation_bps=120.0,
    )

    assert round(degradation, 2) == 28.0
    assert round(edge or 0, 2) == -8.0
    assert NoTradeReason.EDGE_REMAINING_TOO_LOW.value in reasons
