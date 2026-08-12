from __future__ import annotations

import gzip
import json
from pathlib import Path

from hl_observer.backtesting.lead_lag_multitape import discover_sources, load_multitape


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_discovers_live_and_sealed_shards(tmp_path: Path) -> None:
    data = tmp_path / "runtime" / "data"
    _write(data / "bbo_tape.jsonl", [])
    _write(data / "bbo_shards" / "bbo_tape_2.jsonl.gz", [])
    _write(data / "bbo_shards_archive" / "bbo_tape_1.jsonl.gz", [])
    names = {path.name for path in discover_sources(tmp_path)}
    assert names == {"bbo_tape.jsonl", "bbo_tape_1.jsonl.gz", "bbo_tape_2.jsonl.gz"}


def test_multitape_uses_wall_clock_and_deduplicates(tmp_path: Path) -> None:
    data = tmp_path / "runtime" / "data"
    base = 1_786_552_000_000
    shared = {"venue": "HL", "coin": "BTC", "ts_wall_ms": base, "recu_ns": 50, "mid": 100.0, "bid": 99.9, "ask": 100.1}
    _write(data / "bbo_shards_archive" / "bbo_tape_1.jsonl.gz", [
        shared,
        {"venue": "BIN_TRADE", "coin": "BTC", "ts_wall_ms": base + 1, "recu_ns": 60, "px": 100.2, "side": "BUY"},
    ])
    _write(data / "bbo_shards" / "bbo_tape_2.jsonl.gz", [
        shared,
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": base + 2, "recu_ns": 5, "mid": 100.3, "bid": 100.2, "ask": 100.4},
    ])

    tape, meta = load_multitape(tmp_path)
    assert len(tape["BTC"]["HL"]) == 2
    assert len(tape["BTC"]["TRADE"]) == 1
    assert tape["BTC"]["HL"][0][0] == base * 1_000_000
    assert tape["BTC"]["HL"][1][0] == (base + 2) * 1_000_000
    assert meta["duplicates_rejected"] == 1
    assert meta["clock"] == "WALL_MS_NORMALIZED_TO_NS"


def test_cross_session_record_without_wall_clock_is_rejected(tmp_path: Path) -> None:
    data = tmp_path / "runtime" / "data"
    _write(data / "bbo_shards" / "bbo_tape_1.jsonl.gz", [
        {"venue": "HL", "coin": "ETH", "recu_ns": 123, "mid": 10.0, "bid": 9.9, "ask": 10.1},
    ])
    _write(data / "bbo_shards" / "bbo_tape_2.jsonl.gz", [
        {"venue": "BIN_TRADE", "coin": "ETH", "recu_ns": 456, "px": 10.2, "side": "BUY"},
    ])
    tape, meta = load_multitape(tmp_path)
    assert tape == {}
    assert meta["records_without_common_wall_clock"] == 2


def test_loader_is_bounded_by_line_budget(tmp_path: Path) -> None:
    data = tmp_path / "runtime" / "data"
    rows = [
        {"venue": "HL", "coin": "SOL", "ts_wall_ms": 1_786_552_000_000 + i, "mid": 10.0, "bid": 9.9, "ask": 10.1}
        for i in range(20)
    ]
    _write(data / "bbo_tape.jsonl", rows)
    _tape, meta = load_multitape(tmp_path, max_lines=5, time_budget_s=0)
    assert meta["stopped_reason"] == "MAX_LINES_REACHED"
    assert meta["lines_read"] == 6
