from __future__ import annotations

from hl_observer.collection.reconciliation import merge_reconciled_records, reconcile_records


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


def test_live_and_official_archive_sources_share_canonical_venue_identity() -> None:
    live = [
        {
            "source_id": "binance_usdm_public",
            "instrument": "BTCUSDT",
            "channel": "trades",
            "raw_payload": '{"t": 42, "p": "100.0", "q": "2", "T": 1234}',
        }
    ]
    archive = [
        {
            "source_id": "binance_usdm_official_archive",
            "instrument": "BTCUSDT",
            "channel": "trades",
            "raw_payload": {"trade_id": "42", "price": "100", "quantity": "2.0", "time": 1234},
        }
    ]

    report = reconcile_records(live, archive)

    assert report.status == "MATCHED"
    assert report.matched_count == 1
    assert report.value_conflicts == 0


def test_matching_native_id_with_different_trade_value_fails_closed() -> None:
    live = [
        {
            "venue": "bybit",
            "instrument": "BTCUSDT",
            "trade_id": "same",
            "price": "100",
            "quantity": "1",
        }
    ]
    archive = [
        {
            "venue": "bybit",
            "instrument": "BTCUSDT",
            "trade_id": "same",
            "price": "101",
            "quantity": "1",
        }
    ]

    report = reconcile_records(live, archive)

    assert report.status == "MISMATCH"
    assert report.matched_count == 1
    assert report.value_conflicts == 1


def test_sequence_identity_does_not_collapse_distinct_channels() -> None:
    live = [
        {"venue": "okx", "instrument": "BTC-USDT-SWAP", "channel": "trades", "sequence": 7},
        {"venue": "okx", "instrument": "BTC-USDT-SWAP", "channel": "l2", "sequence": 7},
    ]

    report = reconcile_records(live, live)

    assert report.status == "MATCHED"
    assert report.matched_count == 2
    assert report.duplicate_live_keys == 0


def test_merge_prefers_live_and_adds_only_archive_gaps_with_provenance() -> None:
    live = [
        {"venue": "binance", "instrument": "BTCUSDT", "trade_id": "1", "provenance": "live"}
    ]
    archive = [
        {"venue": "binance", "instrument": "BTCUSDT", "trade_id": "1"},
        {"venue": "binance", "instrument": "BTCUSDT", "trade_id": "2"},
    ]

    merged, report = merge_reconciled_records(live, archive)

    assert report.status == "PARTIAL"
    assert [row["trade_id"] for row in merged] == ["1", "2"]
    assert merged[0]["provenance"] == "live"
    assert merged[1]["provenance"] == "official_archive"


def test_malformed_raw_payload_is_safe_and_deterministic() -> None:
    row = {
        "source_id": "gate_public",
        "instrument": "BTC_USDT",
        "raw_payload": "{not-json",
    }
    report = reconcile_records([row], [row])
    assert report.status == "MATCHED"
