from __future__ import annotations

import json
from decimal import Decimal

import pytest

from hl_observer.market_data.live_l2_service import (
    DYNAMIC_L2_RELPATH,
    LiveL2Service,
    LiveL2Snapshot,
    snapshot_from_mapping,
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


def test_live_l2_preserves_invalid_source_timestamp_for_fail_closed_execution(tmp_path):
    now = 1_700_000_000_500
    snapshot = snapshot_from_mapping(
        "BTC",
        {
            "received_ts_ms": now - 1,
            "time": "not-an-integer",
            "levels": [[{"px": "99", "sz": "2"}], [{"px": "101", "sz": "2"}]],
        },
        source="hyperliquid:test:l2Book",
        now_ms=now,
    )

    assert snapshot is not None
    assert snapshot.exchange_ts_ms is None
    assert snapshot.exchange_ts_raw == "not-an-integer"
    assert snapshot.exchange_ts_status == "INVALID"
    write_dynamic_snapshot(tmp_path, snapshot)
    replayed = LiveL2Service(tmp_path).resolve("BTC", now_ms=now, bbo={}, carnet={})
    assert replayed is not None
    assert replayed.exchange_ts_raw == "not-an-integer"
    assert replayed.exchange_ts_status == "INVALID"
    truth = snapshot.execution_truth()
    assert truth is not None
    assert truth.timestamp_refusal_reason(decision_ts_ms=now) == "SOURCE_TIMESTAMP_INVALID"


def test_legacy_second_clock_is_floored_to_ms_without_rejecting_submillisecond_precision():
    snapshot = snapshot_from_mapping(
        "WLD",
        {
            "collecte_ts": 1_700_000_000.5004,
            "hl_bid": 0.385,
            "hl_ask": 0.386,
            "depth_usd": 3_000,
        },
        source="hyperliquid:ws:l2Book:dynamic",
        now_ms=1_700_000_000_700,
    )

    assert snapshot is not None
    assert snapshot.received_ts_ms == 1_700_000_000_500


def test_epoch_seconds_are_floored_at_utc_midnight_and_not_rounded_forward():
    snapshot = snapshot_from_mapping(
        "BTC",
        {
            "collecte_ts": 1_793_145_600.0009,
            "hl_bid": 99.0,
            "hl_ask": 101.0,
        },
        source="recorded:utc-midnight",
        now_ms=1_793_145_600_001,
    )

    assert snapshot is not None
    assert snapshot.received_ts_ms == 1_793_145_600_000


def test_nanosecond_exchange_timestamp_is_preserved_but_rejected_as_malformed_ms():
    timestamp_ns = 1_793_145_600_000_000_000
    snapshot = snapshot_from_mapping(
        "BTC",
        {
            "received_ts_ms": 1_793_145_600_001,
            "exchange_ts_ms": timestamp_ns,
            "bids": [[99.0, 1.0]],
            "asks": [[101.0, 1.0]],
        },
        source="recorded:ns-unit-mismatch",
        now_ms=1_793_145_600_001,
    )

    assert snapshot is not None
    assert snapshot.exchange_ts_raw == timestamp_ns
    assert snapshot.exchange_ts_ms is None
    assert snapshot.exchange_ts_status == "INVALID"
    truth = snapshot.execution_truth()
    assert truth is not None
    assert truth.timestamp_refusal_reason(decision_ts_ms=1_793_145_600_001) == "SOURCE_TIMESTAMP_INVALID"


def test_dynamic_json_preserves_submillisecond_source_time_through_execution_truth(tmp_path):
    now = 1_793_145_600_001
    path = tmp_path / DYNAMIC_L2_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"BTC":{"collecte_ts":1793145600.0009999,"exchange_ts_ms":1793145600000,'
        '"hl_bid":99,"hl_ask":101,"bids":[[99,1]],"asks":[[101,1]]}}',
        encoding="utf-8",
    )

    snapshot = LiveL2Service(tmp_path).resolve("BTC", now_ms=now, bbo={}, carnet={})

    assert snapshot is not None
    assert snapshot.received_ts_ms == 1_793_145_600_000
    assert isinstance(snapshot.received_ts_raw, Decimal)
    assert str(snapshot.received_ts_raw) == "1793145600.0009999"
    assert snapshot.received_ts_unit == "s_since_unix_epoch_utc"
    truth = snapshot.execution_truth()
    assert truth is not None
    assert truth.received_ts_ms == 1_793_145_600_000
    assert str(truth.received_ts_raw) == "1793145600.0009999"
    assert truth.received_ts_unit == "s_since_unix_epoch_utc"

    write_dynamic_snapshot(tmp_path, snapshot)
    restored = LiveL2Service(tmp_path).resolve("BTC", now_ms=now, bbo={}, carnet={})
    assert restored is not None
    assert restored.received_ts_raw == "1793145600.0009999"
    assert restored.execution_truth().received_ts_unit == "s_since_unix_epoch_utc"


def test_service_rejects_non_integer_or_out_of_range_reference_clock(tmp_path):
    service = LiveL2Service(tmp_path)
    payload = {
        "BTC": {
            "ts_ms": 1_700_000_000_000,
            "hl_bid": 99,
            "hl_ask": 101,
        }
    }

    assert service.resolve("BTC", now_ms=1_700_000_000_000.5, bbo=payload, carnet={}) is None
    assert service.resolve(
        "BTC", now_ms=1_700_000_000_000_000_000, bbo=payload, carnet={}
    ) is None


def test_service_rejects_future_local_receipt_even_inside_legacy_skew_tolerance(tmp_path):
    now = 1_700_000_000_000
    service = LiveL2Service(tmp_path, future_skew_ms=100)
    assert service.resolve(
        "BTC",
        now_ms=now,
        bbo={"BTC": {"ts_ms": now + 50, "hl_bid": 99, "hl_ask": 101}},
        carnet={},
    ) is None


def test_live_snapshot_age_does_not_clamp_future_receive_to_zero():
    snapshot = LiveL2Snapshot(
        coin="BTC", best_bid=99, best_ask=101, depth_usd=1_000,
        source="recorded:future", received_ts_ms=1_700_000_000_001,
    )
    with pytest.raises(ValueError, match="received after reference time"):
        snapshot.age_ms(1_700_000_000_000)


def test_live_l2_rejects_fractional_exchange_timestamp_instead_of_truncating():
    now = 1_700_000_000_500
    snapshot = snapshot_from_mapping(
        "BTC",
        {
            "received_ts_ms": now - 1,
            "exchange_ts_ms": now - 2.5,
            "bids": [[99, 2]],
            "asks": [[101, 2]],
        },
        source="recorded:test:l2Book",
        now_ms=now,
    )

    assert snapshot is not None
    assert snapshot.exchange_ts_raw == now - 2.5
    assert snapshot.exchange_ts_status == "INVALID"
    truth = snapshot.execution_truth()
    assert truth is not None
    assert truth.timestamp_refusal_reason(decision_ts_ms=now) == "SOURCE_TIMESTAMP_INVALID"


def test_live_l2_does_not_fabricate_receipt_timestamp_from_current_time():
    now = 1_700_000_000_500
    snapshot = snapshot_from_mapping(
        "BTC",
        {"hl_bid": 99, "hl_ask": 101, "bids": [[99, 1]], "asks": [[101, 1]]},
        source="recorded:missing-receipt",
        now_ms=now,
    )

    assert snapshot is None


def test_live_l2_rejects_overflowing_derived_visible_depth():
    now = 1_700_000_000_500
    snapshot = snapshot_from_mapping(
        "BTC",
        {
            "received_ts_ms": now - 1,
            "exchange_ts_ms": now - 2,
            "bids": [[1e308, 1e308]],
            "asks": [[1e308, 1e308]],
        },
        source="recorded:overflowing-depth",
        now_ms=now,
    )

    assert snapshot is None


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

    def copy_adapter(root, now_ms=None, lecteur_l2=None, **kwargs):
        captured["reader"] = lecteur_l2
        return [], []

    monkeypatch.setattr(runner, "COLLECTEURS", {"copy_vault": copy_adapter})
    runner.tick(tmp_path, now_ms=50_000, moteurs=("copy_vault",))
    assert callable(captured["reader"])
