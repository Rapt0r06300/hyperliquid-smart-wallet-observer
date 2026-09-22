from __future__ import annotations

from hl_observer.datasets.cross_venue_window import (
    PARTIAL,
    REJECT,
    SAFE,
    build_cross_venue_window_manifest,
)


def _component(
    dataset_id: str,
    venue: str,
    family: str,
    symbol: str,
    *,
    start: int = 1_000,
    end: int = 2_000,
    run_id: str = "market-run-1",
    status: str = "SAFE",
) -> dict:
    return {
        "dataset_id": dataset_id,
        "venue": venue,
        "family": family,
        "symbol": symbol,
        "start_ts_ms": start,
        "end_ts_ms": end,
        "collection_run_id": run_id,
        "quality_status": status,
        "validation_allowed": status == "SAFE",
        "asset_verified": True,
    }


def _clean_components() -> list[dict]:
    return [
        _component("hl-l2", "hyperliquid", "l2Book", "BTC"),
        _component("hl-trades", "hyperliquid", "trades", "BTC"),
        _component("bin-l2", "binance", "l2Book", "BTCUSDT"),
        _component("bin-trades", "binance", "trades", "BTCUSDT"),
    ]


def _sync() -> dict:
    return {
        "status": "MATCHED",
        "sample_count": 200,
        "p95_receive_skew_ms": 42.0,
        "max_receive_skew_ms": 90.0,
        "gap_count": 0,
    }


def test_clean_same_run_cross_venue_window_can_be_safe() -> None:
    result = build_cross_venue_window_manifest(
        _clean_components(),
        canonical_coin="BTC",
        required_families_by_venue={
            "hyperliquid": {"l2Book", "trades"},
            "binance": {"l2Book", "trades"},
        },
        instrument_mapping_exact=True,
        sync_report=_sync(),
        min_overlap_ms=500,
    )
    assert result["quality_status"] == SAFE
    assert result["validation_allowed"] is True
    assert result["proof_of_pnl_allowed"] is False
    assert result["collection_run_id"] == "market-run-1"
    assert result["window"]["overlap_ms"] == 1_000
    assert result["quality_reasons"] == []


def test_different_collection_runs_are_never_safe() -> None:
    rows = _clean_components()
    rows[-1]["collection_run_id"] = "market-run-2"
    result = build_cross_venue_window_manifest(
        rows,
        canonical_coin="BTC",
        required_families_by_venue={
            "hyperliquid": {"l2Book", "trades"},
            "binance": {"l2Book", "trades"},
        },
        instrument_mapping_exact=True,
        sync_report=_sync(),
    )
    assert result["quality_status"] == PARTIAL
    assert result["validation_allowed"] is False
    assert "MULTIPLE_OR_UNKNOWN_COLLECTION_RUNS" in result["quality_reasons"]


def test_missing_required_family_or_sync_proof_stays_partial() -> None:
    rows = [
        row
        for row in _clean_components()
        if row["dataset_id"] != "bin-trades"
    ]
    result = build_cross_venue_window_manifest(
        rows,
        canonical_coin="BTC",
        required_families_by_venue={
            "hyperliquid": {"l2Book", "trades"},
            "binance": {"l2Book", "trades"},
        },
        instrument_mapping_exact=True,
        sync_report=None,
    )
    assert result["quality_status"] == PARTIAL
    reasons = result["quality_reasons"]
    assert "MISSING_REQUIRED_COMPONENT:binance:trades" in reasons
    assert "PAIR_SYNC_UNVERIFIED" in reasons
    assert "PAIR_SYNC_SAMPLE_TOO_SMALL" in reasons
    assert "PAIR_SYNC_P95_MISSING" in reasons
    assert "PAIR_SYNC_MAX_MISSING" in reasons


def test_no_temporal_overlap_is_rejected() -> None:
    rows = _clean_components()
    rows[0]["start_ts_ms"] = 3_000
    rows[0]["end_ts_ms"] = 4_000
    result = build_cross_venue_window_manifest(
        rows,
        canonical_coin="BTC",
        required_families_by_venue={
            "hyperliquid": {"l2Book", "trades"},
            "binance": {"l2Book", "trades"},
        },
        instrument_mapping_exact=True,
        sync_report=_sync(),
    )
    assert result["quality_status"] == REJECT
    assert result["validation_allowed"] is False
    assert "NO_TEMPORAL_OVERLAP" in result["quality_reasons"]


def test_sync_gap_is_rejected_even_when_components_are_safe() -> None:
    sync = _sync()
    sync["gap_count"] = 1
    result = build_cross_venue_window_manifest(
        _clean_components(),
        canonical_coin="BTC",
        required_families_by_venue={
            "hyperliquid": {"l2Book", "trades"},
            "binance": {"l2Book", "trades"},
        },
        instrument_mapping_exact=True,
        sync_report=sync,
    )
    assert result["quality_status"] == REJECT
    assert "PAIR_SYNC_GAPS" in result["quality_reasons"]


def test_unverified_mapping_cannot_be_safe() -> None:
    result = build_cross_venue_window_manifest(
        _clean_components(),
        canonical_coin="BTC",
        required_families_by_venue={
            "hyperliquid": {"l2Book", "trades"},
            "binance": {"l2Book", "trades"},
        },
        instrument_mapping_exact=False,
        sync_report=_sync(),
    )
    assert result["quality_status"] == PARTIAL
    assert "INSTRUMENT_MAPPING_UNVERIFIED" in result["quality_reasons"]
