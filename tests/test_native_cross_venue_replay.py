from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.native_cross_venue_replay import (
    scan_native_cross_venue_prefilter,
    snapshot_from_record,
)


def _record(
    venue: str,
    bid: float,
    ask: float,
    ts: int,
    *,
    transport_rtt_ms: float | None = 0.0,
) -> dict:
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
            "transport_rtt_ms": transport_rtt_ms,
            "gap_count": 0,
            "duplicate_count": 0,
            "regression_count": 0,
            "exchange_ts_ms": ts - 5,
            "receive_ts_ms": ts,
        },
        "read_only": True,
        "real_execution": False,
    }


def _write_pair(root: Path, *, transport_rtt_ms: float | None = 0.0) -> None:
    rows = [
        ("bybit", _record("bybit", 99.9, 100.0, 1_000, transport_rtt_ms=transport_rtt_ms)),
        ("okx", _record("okx", 101.5, 101.6, 1_010, transport_rtt_ms=transport_rtt_ms)),
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
    _write_pair(tmp_path)

    report = scan_native_cross_venue_prefilter(
        tmp_path,
        notional_usd=100.0,
        max_rows=100,
    )
    assert report["status"] == "COMPLETE_PREFILTER"
    assert report["candidate_observations"] >= 1
    assert report["taker_taker_positive_fee_floor"] >= 1
    assert report["economic_claim_eligible"] is False
    assert report["closed_cycle_proven"] is False
    assert report["maker_fill_proven"] is False
    assert report["carry_pnl_usd"] == 0.0
    assert report["paper_read_only"] is True
    assert report["real_execution"] is False


def test_native_replay_scans_predeclared_capacity_ladder_by_default(tmp_path: Path) -> None:
    _write_pair(tmp_path)

    report = scan_native_cross_venue_prefilter(tmp_path, max_rows=100)

    assert report["notionals_usd"] == [50.0, 100.0, 250.0, 500.0]
    tested = {float(row["tested_notional_usd"]) for row in report["top_candidates"]}
    assert tested == {50.0, 100.0, 250.0, 500.0}
    assert report["candidate_observations"] >= 4
    assert report["economic_claim_eligible"] is False


def test_native_replay_applies_execution_and_latency_penalties(tmp_path: Path) -> None:
    _write_pair(tmp_path, transport_rtt_ms=20.0)

    baseline = scan_native_cross_venue_prefilter(
        tmp_path,
        notional_usd=100.0,
        max_rows=100,
        execution_buffer_bps=0.0,
        latency_penalty_bps_per_ms=0.0,
    )
    penalized = scan_native_cross_venue_prefilter(
        tmp_path,
        notional_usd=100.0,
        max_rows=100,
        execution_buffer_bps=2.0,
        latency_penalty_bps_per_ms=0.1,
    )

    assert penalized["execution_buffer_bps"] == 2.0
    assert penalized["latency_penalty_bps_per_ms"] == 0.1
    assert penalized["best_conservative_taker_round_trip_net_edge_bps"] < baseline[
        "best_conservative_taker_round_trip_net_edge_bps"
    ]
    assert all(
        float(row["conservative_taker_round_trip_net_edge_bps"])
        <= float(row["taker_taker_round_trip_net_floor_bps"])
        for row in penalized["top_candidates"]
    )


def test_native_replay_charges_recorded_transport_uncertainty(tmp_path: Path) -> None:
    _write_pair(tmp_path, transport_rtt_ms=20.0)

    report = scan_native_cross_venue_prefilter(
        tmp_path,
        notional_usd=100.0,
        max_rows=100,
        execution_buffer_bps=0.0,
        latency_penalty_bps_per_ms=0.1,
    )

    row = report["top_candidates"][0]
    assert row["receive_skew_ms"] == 10.0
    assert row["transport_uncertainty_ms"] == 20.0
    assert row["total_latency_uncertainty_ms"] == 30.0
    assert row["latency_penalty_bps"] == 3.0
    assert row["conservative_taker_round_trip_net_edge_bps"] == (
        row["taker_taker_round_trip_net_floor_bps"] - 3.0
    )


def test_native_replay_fails_closed_without_transport_evidence_for_latency_penalty(
    tmp_path: Path,
) -> None:
    _write_pair(tmp_path, transport_rtt_ms=None)

    report = scan_native_cross_venue_prefilter(
        tmp_path,
        notional_usd=100.0,
        max_rows=100,
        latency_penalty_bps_per_ms=0.1,
    )

    assert report["candidate_observations"] == 0
    assert report["status"] == "COMPLETE_PREFILTER"
