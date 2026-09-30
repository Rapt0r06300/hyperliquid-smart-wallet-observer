from __future__ import annotations

import json
from pathlib import Path

import pytest

import hl_observer.backtesting.lead_lag_certified_backtest as certified


def test_timestamp_float_positive_and_dedupe_helpers() -> None:
    assert certified.certified_event_time_ns({"ts_wall_ms": 1234}) == 1_234_000_000
    assert certified.certified_event_time_ns({"recv_wall_ts_ms": "12.5"}) == 12_500_000
    assert certified.certified_event_time_ns({"recu_ns": 999}) is None
    assert certified.certified_event_time_ns({"ts_wall_ms": 0}) is None
    assert certified.certified_event_time_ns({"ts_wall_ms": "bad"}) is None
    assert certified._flt("1.5") == 1.5
    assert certified._flt(float("inf")) is None
    assert certified._flt("bad") is None
    assert certified._positive(1) == 1.0
    assert certified._positive(0) is None

    event = {"event_id": "e1", "venue": "HL", "coin": "btc"}
    assert certified._dedupe_key(event, 1) == ("event_id", "e1")
    trade = {"venue": "BIN_TRADE", "coin": "btc", "px": 10, "side": "BUY", "sz": 2}
    key = certified._dedupe_key(trade, 3)
    assert key[:3] == ("BIN_TRADE", "BTC", 3)
    book = {"venue": "HL", "coin": "eth", "bid": 9, "ask": 11, "mid": 10}
    assert certified._dedupe_key(book, 4)[:3] == ("HL", "ETH", 4)


def test_load_certified_tape_filters_dedupes_and_reports_meta(tmp_path, monkeypatch) -> None:
    path = tmp_path / "tape.jsonl"
    rows = [
        {"coin": "BTC", "venue": "HL", "ts_wall_ms": 1000, "mid": 100, "bid": 99, "ask": 101, "bid_sz": 2, "ask_sz": 3, "event_id": "h1"},
        {"coin": "BTC", "venue": "HL", "ts_wall_ms": 1000, "mid": 100, "event_id": "h1"},
        {"coin": "BTC", "venue": "BIN_TRADE", "recv_wall_ts_ms": 1001, "px": 100.5, "side": "BUY", "sz": 1, "event_id": "t1"},
        {"coin": "BTC", "venue": "BIN_TRADE", "recv_wall_ts_ms": 1002, "px": 100.4, "side": "BAD", "event_id": "t2"},
        {"coin": "ETH", "venue": "HL", "recu_ns": 123, "mid": 200},
        {"coin": "ETH", "venue": "OTHER", "ts_wall_ms": 1000, "mid": 200},
        {"coin": "ETH", "venue": "HL", "ts_wall_ms": 1000, "mid": 0},
        {"venue": "HL", "ts_wall_ms": 1000, "mid": 1},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    monkeypatch.setattr(certified.base, "_iter_lines", lambda source: source.read_text(encoding="utf-8").splitlines())
    tape, meta = certified.load_certified_tape(tmp_path, sources=[path], return_meta=True)
    assert len(tape["BTC"]["HL"]) == 1
    assert len(tape["BTC"]["TRADE"]) == 1
    assert tape["BTC"]["HL"][0][1] == 100.0
    assert meta["duplicates_rejected"] == 1
    assert meta["uncertifiable_clock_rows"] == 1
    assert meta["unsupported_rows"] == 1
    assert meta["invalid_rows"] >= 3
    assert meta["wall_clock_required"] is True
    assert meta["monotonic_only_rows_eligible_for_economic_proof"] is False
    assert meta["sources_count"] == 1


def test_partition_and_certification() -> None:
    tape = {"BTC": {}, "ETH": {}, "SOL": {}}
    row = certified.partition_universe(tape, ["eth", "DOGE"])
    assert row["test"] == ["BTC", "SOL"]
    assert row["control"] == ["ETH"]
    assert row["ignored_controls_missing_from_tape"] == ["DOGE"]
    cert = certified._certification({"uncertifiable_clock_rows": 7})
    assert cert["policy"] == certified.CERTIFIED_TIMESTAMP_POLICY
    assert cert["monotonic_only_rows_rejected"] == 7
    assert cert["archive_rows_preserved"] is True


def test_backtest_certified_empty_and_no_observable_horizon(monkeypatch) -> None:
    monkeypatch.setattr(
        certified,
        "load_certified_tape",
        lambda *args, **kwargs: ({}, {"uncertifiable_clock_rows": 2}),
    )
    row = certified.backtest_certified(".")
    assert row["statut"] == "NEED_MORE_DATA"
    assert row["detail"] == "tape certifiee vide"
    assert row["timestamp_certification"]["monotonic_only_rows_rejected"] == 2

    tape = {"BTC": {"HL": [(1, 100, 99, 101, None, None)] * 4, "BIN": [], "TRADE": []}}
    monkeypatch.setattr(
        certified,
        "load_certified_tape",
        lambda *args, **kwargs: (tape, {"uncertifiable_clock_rows": 0}),
    )
    row = certified.backtest_certified(".", horizons_ms=(10, 20))
    assert row["statut"] == "NEED_MORE_DATA"
    assert "aucun horizon observable" in row["detail"]


def test_backtest_certified_not_enough_shocks(monkeypatch) -> None:
    hl = [
        (1_000_000_000 + i * 100_000_000, 100.0 + i, 99.0 + i, 101.0 + i, 10.0, 10.0)
        for i in range(6)
    ]
    tape = {"BTC": {"HL": hl, "BIN": [], "TRADE": [(1_050_000_000, 100.0, 1.0)]}}
    monkeypatch.setattr(
        certified,
        "load_certified_tape",
        lambda *args, **kwargs: (tape, {"uncertifiable_clock_rows": 0}),
    )
    monkeypatch.setattr(certified.base, "distribution_intervalles", lambda rows: {"p50_ms": 100.0})
    monkeypatch.setattr(certified.base, "detecter_chocs", lambda rows, seuil_bps: [])
    row = certified.backtest_certified(".", horizons_ms=(250,), min_chocs=2)
    assert row["statut"] == "NEED_MORE_DATA"
    assert row["chocs_test"] == 0
    assert row["cible"] == 2
    assert row["horizons_observables"] == [250.0]
