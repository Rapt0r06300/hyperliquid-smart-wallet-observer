from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.native_cross_venue_replay import (
    scan_native_cross_venue_prefilter,
    snapshot_from_record,
)


def _record(venue: str, bid: float, ask: float, ts: int) -> dict:
    return {
        "schema_version": "hypersmart.tick.v1",
        "source_id": f"{venue}_public_readonly",
        "channel": "native_market",
        "instrument": "BTC",
        "event_kind": "SNAPSHOT",
        "exchange_ts_ms": ts - 5,
        "received_ts_ms": ts,
        "written_ts_ms": ts + 1,
        "local_monotonic_ns": ts * 1_000_000,
        "connection_id": f"{venue}-1",
        "sequence": 10,
        "gap_count": 0,
        "raw_sha256": f"{venue}-{ts}",
        "raw_payload": "{}",
        "provenance": {
            "access": "public_read_only",
            "authenticated": False,
            "transport": "websocket",
        },
        "parsed_summary": {
            "venue": venue,
            "coin": "BTC",
            "clock_domain_id": "runner-1",
            "exchange_symbol": "BTC",
            "bid": bid,
            "ask": ask,
            "bids": [[bid, 10.0]],
            "asks": [[ask, 10.0]],
            "quality": "EXPLOITABLE",
            "sequence": 10,
            "connection_id": f"{venue}-1",
            "receive_mono_ns": ts * 1_000_000,
            "gap_count": 0,
            "duplicate_count": 0,
            "regression_count": 0,
            "exchange_ts_ms": ts - 5,
            "receive_ts_ms": ts,
        },
        "read_only": True,
        "real_execution": False,
    }


def test_snapshot_from_record_requires_full_l2() -> None:
    record = _record("okx", 101.5, 101.6, 1_010)
    snapshot = snapshot_from_record(record)
    assert snapshot is not None
    assert snapshot.venue == "okx"
    assert snapshot.bids[0].price == 101.5

    broken = _record("okx", 101.5, 101.6, 1_010)
    broken["parsed_summary"]["bids"] = []
    assert snapshot_from_record(broken) is None


def test_native_replay_finds_fee_aware_cross_venue_candidate(tmp_path: Path) -> None:
    root = tmp_path
    rows = [
        ("bybit", _record("bybit", 99.9, 100.0, 1_000)),
        ("okx", _record("okx", 101.5, 101.6, 1_010)),
    ]
    for venue, row in rows:
        path = (
            root
            / "runtime"
            / "data"
            / "market_ticks"
            / f"{venue}_public_readonly"
            / "native_market"
            / "BTC"
            / "ticks.current.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    report = scan_native_cross_venue_prefilter(
        root,
        notional_usd=100.0,
        max_rows=100,
    )
    assert report["status"] == "COMPLETE_PREFILTER"
    assert report["candidate_observations"] >= 1
    assert report["taker_taker_positive_fee_floor"] >= 1
    assert report["economic_claim_eligible"] is False
    assert report["maker_fill_proven"] is False
