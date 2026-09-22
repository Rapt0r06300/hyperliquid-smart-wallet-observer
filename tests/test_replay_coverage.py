from __future__ import annotations

from hl_observer.datasets.replay_coverage import build_safe_coverage_matrix


def _manifest(
    *,
    venue: str,
    family: str,
    symbol: str,
    start: int,
    end: int,
    dataset_id: str,
    safe: bool = True,
    verified: bool = True,
):
    return {
        "dataset_id": dataset_id,
        "venue": venue,
        "family": family,
        "symbol": symbol,
        "start_ts_ms": start,
        "end_ts_ms": end,
        "event_count": 10,
        "bytes": 100,
        "quality_status": "SAFE" if safe else "PARTIAL",
        "validation_allowed": safe,
        "asset_verified": verified,
    }


def test_safe_coverage_matrix_ignores_unverified_and_partial() -> None:
    matrix = build_safe_coverage_matrix(
        [
            _manifest(
                venue="bybit",
                family="l2Book",
                symbol="BTCUSDT",
                start=1000,
                end=2000,
                dataset_id="safe",
            ),
            _manifest(
                venue="bybit",
                family="trades",
                symbol="BTCUSDT",
                start=1000,
                end=2000,
                dataset_id="partial",
                safe=False,
            ),
            _manifest(
                venue="okx",
                family="l2Book",
                symbol="BTC-USDT-SWAP",
                start=1000,
                end=2000,
                dataset_id="unverified",
                verified=False,
            ),
        ]
    )
    assert matrix["safe_partitions"] == 1
    assert matrix["coins"] == ["BTC"]
    assert matrix["rows"][0]["dataset_ids"] == ["safe"]
    assert matrix["authoritative_for_replay"] is False


def test_safe_coverage_matrix_merges_overlapping_intervals() -> None:
    matrix = build_safe_coverage_matrix(
        [
            _manifest(
                venue="bybit",
                family="l2Book",
                symbol="BTCUSDT",
                start=1000,
                end=2000,
                dataset_id="a",
            ),
            _manifest(
                venue="bybit",
                family="l2Book",
                symbol="BTCUSDT",
                start=1500,
                end=3000,
                dataset_id="b",
            ),
        ]
    )
    row = matrix["rows"][0]
    assert row["shard_count"] == 2
    assert row["event_count"] == 20
    assert row["intervals"] == [{"start_ts_ms": 1000, "end_ts_ms": 3000}]
    assert row["covered_ms"] == 2000


def test_safe_coverage_matrix_canonicalizes_cross_venue_symbols() -> None:
    matrix = build_safe_coverage_matrix(
        [
            _manifest(
                venue="bybit",
                family="l2Book",
                symbol="ETHUSDT",
                start=1000,
                end=2000,
                dataset_id="bybit",
            ),
            _manifest(
                venue="okx",
                family="l2Book",
                symbol="ETH-USDT-SWAP",
                start=1000,
                end=2000,
                dataset_id="okx",
            ),
        ]
    )
    assert matrix["coins"] == ["ETH"]
    assert matrix["venues"] == ["bybit", "okx"]
