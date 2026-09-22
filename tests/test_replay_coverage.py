from __future__ import annotations

from hl_observer.datasets.replay_coverage import (
    assess_replay_contract,
    build_safe_coverage_matrix,
)


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


def test_replay_contract_requires_common_safe_overlap() -> None:
    matrix = build_safe_coverage_matrix(
        [
            _manifest(
                venue="bybit",
                family="l2Book",
                symbol="BTCUSDT",
                start=1000,
                end=5000,
                dataset_id="bb-l2",
            ),
            _manifest(
                venue="bybit",
                family="trades",
                symbol="BTCUSDT",
                start=1500,
                end=4500,
                dataset_id="bb-trades",
            ),
            _manifest(
                venue="okx",
                family="l2Book",
                symbol="BTC-USDT-SWAP",
                start=2000,
                end=4000,
                dataset_id="okx-l2",
            ),
            _manifest(
                venue="okx",
                family="trades",
                symbol="BTC-USDT-SWAP",
                start=2500,
                end=3500,
                dataset_id="okx-trades",
            ),
        ]
    )
    report = assess_replay_contract(
        matrix,
        coin="BTC",
        requirements={
            "bybit": ["l2Book", "trades"],
            "okx": ["l2Book", "trades"],
        },
        min_overlap_ms=500,
    )
    assert report["status"] == "READY"
    assert report["overlap_start_ts_ms"] == 2500
    assert report["overlap_end_ts_ms"] == 3500
    assert report["overlap_ms"] == 1000


def test_replay_contract_missing_family_fails_closed() -> None:
    matrix = build_safe_coverage_matrix(
        [
            _manifest(
                venue="bybit",
                family="l2Book",
                symbol="ETHUSDT",
                start=1000,
                end=5000,
                dataset_id="bb-l2",
            )
        ]
    )
    report = assess_replay_contract(
        matrix,
        coin="ETH",
        requirements={"bybit": ["l2Book", "trades"]},
    )
    assert report["status"] == "NO_GO"
    assert report["missing"] == ["bybit:trades"]


def test_replay_contract_disjoint_intervals_are_no_go() -> None:
    matrix = build_safe_coverage_matrix(
        [
            _manifest(
                venue="bybit",
                family="l2Book",
                symbol="SOLUSDT",
                start=1000,
                end=1500,
                dataset_id="l2",
            ),
            _manifest(
                venue="bybit",
                family="trades",
                symbol="SOLUSDT",
                start=2000,
                end=2500,
                dataset_id="trades",
            ),
        ]
    )
    report = assess_replay_contract(
        matrix,
        coin="SOL",
        requirements={"bybit": ["l2Book", "trades"]},
    )
    assert report["status"] == "NO_GO"
    assert report["overlap_ms"] == 0
