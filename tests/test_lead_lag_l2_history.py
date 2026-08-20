from __future__ import annotations

import gzip
import json
from pathlib import Path

from hl_observer.simulation.lead_lag_l2_history import (
    discover_l2_sources,
    load_l2_history,
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


def test_loader_is_bounded(tmp_path: Path) -> None:
    directory = tmp_path / "runtime" / "data" / "market_ticks"
    _write(
        directory / "hyperliquid_market_ticks.current.jsonl",
        [_record(ts_ms=1_786_552_000_000 + i, raw_sha=str(i)) for i in range(10)],
    )
    _history, meta = load_l2_history(tmp_path, max_lines=3, time_budget_s=0)
    assert meta["stopped_reason"] == "MAX_LINES_REACHED"
    assert meta["lines_read"] == 4
