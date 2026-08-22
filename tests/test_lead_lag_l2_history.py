from __future__ import annotations

import gzip
import json
from pathlib import Path

from hl_observer.simulation.lead_lag_l2_history import (
    discover_l2_sources,
    load_l2_history,
    load_market_microstructure_event_windows,
    load_market_microstructure_history,
    public_trades_from_tick,
    snapshot_from_tick,
)


def _record(*, coin: str = "ETH", ts_ms: int = 1_786_552_000_000, raw_sha: str = "a") -> dict:
    message = {
        "channel": "l2Book",
        "data": {
            "coin": coin,
            "time": ts_ms - 1,
            "levels": [
                [{"px": "100", "sz": "2"}, {"px": "99", "sz": "3"}],
                [{"px": "101", "sz": "4"}, {"px": "102", "sz": "5"}],
            ],
        },
    }
    return {
        "schema_version": "hypersmart.tick.v1",
        "channel": "l2Book",
        "instrument": coin,
        "received_ts_ms": ts_ms,
        "written_ts_ms": ts_ms + 3,
        "connection_id": "ws-test",
        "sequence": 7,
        "raw_sha256": raw_sha,
        "raw_payload": json.dumps(message),
        "parsed_summary": {
            "feed_quality_score": 96.0,
            "data_gate_ready": True,
            "quality_reasons": [],
        },
        "read_only": True,
        "real_execution": False,
    }


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _trade_record(*, ts_ms: int = 1_786_552_000_000, trade_id: int = 7) -> dict:
    message = {
        "channel": "trades",
        "data": [
            {
                "coin": "ETH",
                "side": "A",
                "px": "100",
                "sz": "0.4",
                "time": ts_ms - 2,
                "tid": trade_id,
            }
        ],
    }
    return {
        "channel": "trades",
        "instrument": "ETH",
        "received_ts_ms": ts_ms,
        "written_ts_ms": ts_ms + 4,
        "raw_sha256": f"trade-{trade_id}",
        "raw_payload": json.dumps(message),
        "parsed_summary": {
            "quality_by_coin": {
                "ETH": {
                    "feed_quality_score": 93.0,
                    "data_gate_ready": True,
                    "quality_reasons": [],
                }
            }
        },
        "read_only": True,
        "real_execution": False,
    }


def test_snapshot_recovers_real_prices_sizes_and_depth() -> None:
    snapshot = snapshot_from_tick(_record())
    assert snapshot is not None
    assert snapshot["bid"] == 100.0
    assert snapshot["ask"] == 101.0
    assert snapshot["bid_size"] == 2.0
    assert snapshot["ask_size"] == 4.0
    assert snapshot["bid_top_usd"] == 200.0
    assert snapshot["ask_top_usd"] == 404.0
    assert snapshot["bid_depth_usd"] == 497.0
    assert snapshot["ask_depth_usd"] == 914.0
    assert snapshot["data_origin"] == "RECORDED_REAL"
    assert snapshot["received_ts_ms"] == 1_786_552_000_000
    assert snapshot["written_ts_ms"] == 1_786_552_000_003
    assert snapshot["observable_at_ms"] == 1_786_552_000_003
    assert snapshot["ts_ms"] == 1_786_552_000_003
    assert snapshot["connection_id"] == "ws-test"
    assert snapshot["feed_quality_score"] == 96.0
    assert snapshot["data_gate_ready"] is True
    assert snapshot["real_execution"] is False


def test_non_l2_or_clockless_rows_fail_closed() -> None:
    non_l2 = _record()
    non_l2["channel"] = "bbo"
    assert snapshot_from_tick(non_l2) is None

    clockless = _record()
    clockless.pop("received_ts_ms")
    assert snapshot_from_tick(clockless) is None

    not_durable = _record()
    not_durable.pop("written_ts_ms")
    assert snapshot_from_tick(not_durable) is None

    write_before_receive = _record()
    write_before_receive["written_ts_ms"] = write_before_receive["received_ts_ms"] - 1
    assert snapshot_from_tick(write_before_receive) is None


def test_public_trade_uses_durable_clock_and_real_aggressor_side() -> None:
    trades = public_trades_from_tick(_trade_record())
    assert len(trades) == 1
    assert trades[0]["side"] == "A"
    assert trades[0]["px"] == 100.0
    assert trades[0]["sz"] == 0.4
    assert trades[0]["ts_ms"] == 1_786_552_000_004
    assert trades[0]["data_gate_ready"] is True


def test_microstructure_loader_reads_books_and_trades_once(tmp_path: Path) -> None:
    directory = tmp_path / "runtime" / "data" / "market_ticks"
    _write(
        directory / "hyperliquid_market_ticks.current.jsonl",
        [_record(), _trade_record()],
    )
    books, trades, meta = load_market_microstructure_history(
        tmp_path, time_budget_s=0
    )
    assert len(books["ETH"]) == 1
    assert len(trades["ETH"]) == 1
    assert meta["l2_rows"] == 1
    assert meta["trade_rows"] == 1
    assert meta["clock"] == "DURABLE_OBSERVABLE_MAX_RECEIVE_WRITE_MS"


def test_loader_discovers_current_and_shards_deduplicates_and_sorts(tmp_path: Path) -> None:
    directory = tmp_path / "runtime" / "data" / "market_ticks"
    first = _record(ts_ms=1_786_552_000_002, raw_sha="second")
    second = _record(ts_ms=1_786_552_000_001, raw_sha="first")
    duplicate = dict(second)
    _write(directory / "hyperliquid_market_ticks.current.jsonl", [first, duplicate])
    _write(
        directory / "shards" / "hyperliquid_market_ticks.1-2.1.jsonl.gz",
        [second],
    )

    sources = discover_l2_sources(tmp_path)
    assert len(sources) == 2
    history, meta = load_l2_history(tmp_path, time_budget_s=0)
    assert [row["ts_ms"] for row in history["ETH"]] == [
        1_786_552_000_004,
        1_786_552_000_005,
    ]
    assert meta["duplicates_rejected"] == 1
    assert meta["l2_rows"] == 2
    assert meta["clock"] == "DURABLE_OBSERVABLE_MAX_RECEIVE_WRITE_MS"


def test_discovery_includes_root_shards_and_never_evicts_current(tmp_path: Path) -> None:
    directory = tmp_path / "runtime" / "data" / "market_ticks"
    current = directory / "hyperliquid_market_ticks.current.jsonl"
    root_old = directory / "hyperliquid_market_ticks.1-2.1.jsonl.gz"
    root_new = directory / "hyperliquid_market_ticks.3-4.2.jsonl.gz"
    legacy = directory / "shards" / "hyperliquid_market_ticks.0-1.0.jsonl.gz"
    for path in (current, root_old, root_new, legacy):
        _write(path, [_record(raw_sha=path.name)])

    sources = discover_l2_sources(tmp_path, max_files=2)
    assert [path.name for path in sources] == [current.name, root_new.name]
    assert all(path.is_file() for path in sources)


def test_loader_is_bounded(tmp_path: Path) -> None:
    directory = tmp_path / "runtime" / "data" / "market_ticks"
    _write(
        directory / "hyperliquid_market_ticks.current.jsonl",
        [_record(ts_ms=1_786_552_000_000 + i, raw_sha=str(i)) for i in range(10)],
    )
    _history, meta = load_l2_history(tmp_path, max_lines=3, time_budget_s=0)
    assert meta["stopped_reason"] == "MAX_LINES_REACHED"
    assert meta["lines_read"] == 4


def test_windowed_loader_reads_only_overlapping_shards_before_line_budget(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "runtime" / "data" / "market_ticks"
    old_start = 1_786_500_000_000
    target_start = 1_786_552_000_000
    _write(
        directory
        / "shards"
        / f"hyperliquid_market_ticks.{old_start}-{old_start + 100}.1.jsonl.gz",
        [_record(ts_ms=old_start + i, raw_sha=f"old-{i}") for i in range(20)],
    )
    target_path = (
        directory
        / "shards"
        / f"hyperliquid_market_ticks.{target_start}-{target_start + 100}.2.jsonl.gz"
    )
    _write(
        target_path,
        [
            _record(ts_ms=target_start + 5, raw_sha="target-book"),
            _trade_record(ts_ms=target_start + 6, trade_id=99),
        ],
    )

    books, trades, meta = load_market_microstructure_history(
        tmp_path,
        max_lines=3,
        time_budget_s=0,
        start_ms=target_start,
        end_ms=target_start + 100,
    )

    assert len(books["ETH"]) == 1
    assert len(trades["ETH"]) == 1
    assert meta["stopped_reason"] == "COMPLETED"
    assert meta["source_time_filter_applied"] is True
    assert meta["requested_start_ms"] == target_start
    assert meta["requested_end_ms"] == target_start + 100
    assert meta["sources"] == [target_path.relative_to(tmp_path).as_posix()]


def test_windowed_loader_filters_current_rows_outside_requested_range(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "runtime" / "data" / "market_ticks"
    target = 1_786_552_000_000
    _write(
        directory / "hyperliquid_market_ticks.current.jsonl",
        [
            _record(ts_ms=target - 100, raw_sha="before"),
            _record(ts_ms=target + 5, raw_sha="inside"),
            _record(ts_ms=target + 100, raw_sha="after"),
        ],
    )

    history, meta = load_l2_history(
        tmp_path,
        time_budget_s=0,
        start_ms=target,
        end_ms=target + 10,
    )

    assert [row["raw_sha256"] for row in history["ETH"]] == ["inside"]
    assert meta["rows_outside_window"] == 2


def test_sparse_event_windows_each_receive_an_independent_line_budget(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "runtime" / "data" / "market_ticks" / "shards"
    first = 1_786_552_000_000
    second = first + 7 * 24 * 60 * 60 * 1_000
    for index, timestamp in enumerate((first, second), start=1):
        _write(
            directory
            / f"hyperliquid_market_ticks.{timestamp - 20}-{timestamp + 20}.{index}.jsonl.gz",
            [
                _record(ts_ms=timestamp, raw_sha=f"book-{index}"),
                _trade_record(ts_ms=timestamp + 1, trade_id=index),
            ],
        )

    books, trades, meta = load_market_microstructure_event_windows(
        tmp_path,
        [first, second],
        before_ms=10,
        after_ms=20,
        max_lines_per_window=2,
        time_budget_s_per_window=0,
    )

    assert [row["raw_sha256"] for row in books["ETH"]] == ["book-1", "book-2"]
    assert [row["trade_id"] for row in trades["ETH"]] == ["1", "2"]
    assert meta["merged_window_count"] == 2
    assert meta["lines_read"] == 4
    assert meta["l2_rows"] == 2
    assert meta["trade_rows"] == 2
    assert meta["stopped_reason"] == "COMPLETED"
    assert all(item["stopped_reason"] == "COMPLETED" for item in meta["per_window"])
