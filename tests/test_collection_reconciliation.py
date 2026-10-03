from __future__ import annotations

from hl_observer.collection.reconciliation import reconcile_records


def test_reconciliation_matches_same_event_ids() -> None:
    report = reconcile_records(
        [{"event_id": "a"}, {"event_id": "b"}],
        [{"event_id": "a"}, {"event_id": "b"}],
    )
    assert report.status == "MATCHED"
    assert report.matched_count == 2


def test_reconciliation_exposes_missing_records() -> None:
    report = reconcile_records(
        [{"event_id": "a"}],
        [{"event_id": "a"}, {"event_id": "b"}],
    )
    assert report.status == "PARTIAL"
    assert report.missing_from_live == 1


def test_native_ids_are_scoped_by_venue_and_instrument() -> None:
    report = reconcile_records(
        [{"venue": "bybit", "instrument": "BTCUSDT", "trade_id": "42"}],
        [{"venue": "okx", "instrument": "BTC-USDT-SWAP", "trade_id": "42"}],
    )
    assert report.status == "MISMATCH"
    assert report.matched_count == 0


def test_same_timestamp_with_distinct_trade_ids_is_retained() -> None:
    rows = [
        {"venue": "bybit", "instrument": "BTCUSDT", "trade_id": "a", "exchange_ts_ms": 1},
        {"venue": "bybit", "instrument": "BTCUSDT", "trade_id": "b", "exchange_ts_ms": 1},
    ]
    report = reconcile_records(rows, rows)
    assert report.status == "MATCHED"
    assert report.matched_count == 2
    assert report.duplicate_live_keys == 0


def test_raw_payload_hash_is_stable_across_mapping_order() -> None:
    live = [{"venue": "gate", "instrument": "BTC_USDT", "raw_payload": {"p": "1", "q": "2"}}]
    reference = [{"venue": "gate", "instrument": "BTC_USDT", "raw_payload": {"q": "2", "p": "1"}}]
    assert reconcile_records(live, reference).status == "MATCHED"
