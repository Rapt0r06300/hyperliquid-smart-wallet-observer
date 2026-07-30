from __future__ import annotations

import json

from hl_observer.market_data.live_l2_service import (
    LiveL2Service,
    LiveL2Snapshot,
    write_dynamic_snapshot,
)


def test_bbo_ts_ms_is_recognized_as_fresh(tmp_path):
    now = 1_700_000_000_500
    service = LiveL2Service(tmp_path, max_age_ms=1_000)
    snapshot = service.resolve(
        "BTC",
        now_ms=now,
        bbo={
            "BTC": {
                "coin": "BTC",
                "ts_ms": now - 200,
                "hl_bid": 60_000,
                "hl_ask": 60_001,
                "taille_top_usd": 25_000,
            }
        },
        carnet={},
    )
    assert snapshot is not None
    assert snapshot.source == "hyperliquid:ws:bbo"
    assert snapshot.age_ms(now) == 200


def test_service_rejects_stale_crossed_and_future_books(tmp_path):
    now = 1_700_000_000_000
    service = LiveL2Service(tmp_path, max_age_ms=1_000, future_skew_ms=100)
    assert service.resolve(
        "BTC",
        now_ms=now,
        bbo={"BTC": {"ts_ms": now - 1_001, "hl_bid": 100, "hl_ask": 101}},
        carnet={},
    ) is None
    assert service.resolve(
        "BTC",
        now_ms=now,
        bbo={"BTC": {"ts_ms": now, "hl_bid": 102, "hl_ask": 101}},
        carnet={},
    ) is None
    assert service.resolve(
        "BTC",
        now_ms=now,
        bbo={"BTC": {"ts_ms": now + 101, "hl_bid": 100, "hl_ask": 101}},
        carnet={},
    ) is None


def test_full_dynamic_book_yields_strict_execution_truth(tmp_path):
    now = 1_700_000_000_000
    observed = LiveL2Snapshot(
        coin="ETH",
        best_bid=2_999,
        best_ask=3_001,
        depth_usd=12_000,
        source="hyperliquid:ws:l2Book:dynamic",
        received_ts_ms=now - 10,
        exchange_ts_ms=now - 20,
        bids=((2_999.0, 2.0), (2_998.0, 3.0)),
        asks=((3_001.0, 2.0), (3_002.0, 3.0)),
    )
    write_dynamic_snapshot(tmp_path, observed)

    resolved = LiveL2Service(tmp_path).resolve("ETH", now_ms=now, bbo={}, carnet={})
    assert resolved is not None
    truth = resolved.execution_truth()
    assert truth is not None
    assert truth.best_bid == 2_999
    assert truth.best_ask == 3_001
    assert truth.data_origin == "REAL"


def test_injected_reader_is_explicit_and_freshest(tmp_path):
    calls: list[str] = []
    now = 1_700_000_000_000

    def reader(coin: str):
        calls.append(coin)
        return {
            "hl_bid": 99,
            "hl_ask": 101,
            "depth_usd": 2_000,
            "received_ts_ms": now,
            "source": "fake-explicit-reader",
        }

    service = LiveL2Service(tmp_path, on_demand_reader=reader)
    result = service.resolve(
        "SOL",
        now_ms=now,
        bbo={"SOL": {"ts_ms": now - 100, "hl_bid": 98, "hl_ask": 102}},
        carnet={},
    )
    assert calls == ["SOL"]
    assert result is not None
    assert result.source == "fake-explicit-reader"


def test_service_does_not_invent_network_or_full_depth(tmp_path):
    now = 1_700_000_000_000
    result = LiveL2Service(tmp_path).resolve(
        "HYPE",
        now_ms=now,
        bbo={"HYPE": {"ts_ms": now, "hl_bid": 40, "hl_ask": 40.1, "taille_top_usd": 100}},
        carnet={},
    )
    assert result is not None
    assert result.execution_truth() is None
    assert result.depth_usd == 100


def test_dynamic_writer_keeps_levels_and_provenance(tmp_path):
    snapshot = LiveL2Snapshot(
        coin="SOL",
        best_bid=149,
        best_ask=150,
        depth_usd=1_000,
        source="hyperliquid:ws:l2Book:dynamic",
        received_ts_ms=1_700_000_000_000,
        bids=((149.0, 2.0),),
        asks=((150.0, 2.0),),
    )
    write_dynamic_snapshot(tmp_path, snapshot)
    raw = json.loads(
        (tmp_path / "runtime" / "data" / "raw_l2_live.json").read_text(encoding="utf-8")
    )
    assert raw["SOL"]["bids"] == [[149.0, 2.0]]
    assert raw["SOL"]["asks"] == [[150.0, 2.0]]
    assert raw["SOL"]["source"] == "hyperliquid:ws:l2Book:dynamic"


def test_experimental_runner_injects_canonical_reader(tmp_path, monkeypatch):
    from hl_observer.experimental import runner

    captured = {}

    def copy_adapter(root, now_ms=None, lecteur_l2=None):
        captured["reader"] = lecteur_l2
        return [], []

    monkeypatch.setattr(runner, "COLLECTEURS", {"copy_vault": copy_adapter})
    runner.tick(tmp_path, now_ms=50_000, moteurs=("copy_vault",))
    assert callable(captured["reader"])
