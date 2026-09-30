from __future__ import annotations

import json

import pytest

from hl_observer.collection.bitget_market_data import BitgetMarketState, parse_bitget_instruments
from hl_observer.collection.gate_market_data import GateMarketState, parse_gate_contracts
from hl_observer.data_sources.market_backfill import (
    BackfillRequest,
    HistoricalBackfillHub,
    HistoricalDataType,
    HistoricalRecord,
    LocalFileAdapter,
    TardisFileAdapter,
    build_official_adapters,
)
from hl_observer.markets.universal_registry import (
    AvailabilityStatus,
    DiscoveryEventType,
    UniversalMarketRegistry,
)
from hl_observer.replay.data_quality import (
    ReplayQuality,
    determine_replay_quality,
    order_point_in_time,
    validate_historical_record,
)


def test_registry_aggregates_statuses_without_promoting_discovery_only() -> None:
    registry = UniversalMarketRegistry(native_venues={"bybit", "gate", "bitget"})
    registry.register("XYZ", "bybit", "XYZUSDT", native=True, historical=True)
    registry.register("XYZ", "gate", "XYZ_USDT", native=True)
    registry.register("XYZ", "kucoin", "XYZ/USDT:USDT", discovery=True)

    market = registry.market("XYZ")
    assert market.venue_count == 3
    assert market.native_venue_count == 2
    assert market.instruments_for_venue("kucoin")[0].status is AvailabilityStatus.DISCOVERY_ONLY
    assert market.hot_path_venues == ("bybit", "gate")


def test_registry_preserves_multiple_instruments_on_one_venue() -> None:
    registry = UniversalMarketRegistry(native_venues={"binance"})

    registry.register(
        "BTC",
        "binance",
        "BTC/USDT",
        native=True,
        market_type="spot",
        quote="USDT",
    )
    registry.register(
        "BTC",
        "binance",
        "BTC/USDT:USDT",
        native=True,
        market_type="perp",
        quote="USDT",
        settle="USDT",
        linear=True,
        contract_size=1.0,
    )

    instruments = registry.market("BTC").instruments_for_venue("binance")
    assert [item.market_type for item in instruments] == ["perp", "spot"]
    assert len({item.identity for item in instruments}) == 2
    assert all(item.status is AvailabilityStatus.NATIVE_LIVE for item in instruments)


def test_registry_dump_load_preserves_useful_state(tmp_path) -> None:
    registry = UniversalMarketRegistry(native_venues={"bybit"})
    registry.register(
        "BTC",
        "bybit",
        "BTC/USDT:USDT",
        native=True,
        historical=True,
        discovery=True,
        quote="USDT",
        settle="USDT",
        linear=True,
        contract_size=1.0,
        first_observed_at_ms=10,
        last_observed_at_ms=20,
    )
    registry.update_metrics("BTC", replay_quality="gold")
    registry.apply_snapshot(
        [{"coin": "ETH", "venue": "bybit", "symbol": "ETHUSDT", "perpetual": True}],
        observed_at_ms=30,
    )
    path = tmp_path / "registry.json"
    registry.dump(path)

    restored = UniversalMarketRegistry.load(path)

    instrument = restored.market("BTC").instruments_for_venue("bybit")[0]
    assert instrument.quote == "USDT"
    assert instrument.settle == "USDT"
    assert instrument.linear is True
    assert instrument.contract_size == 1.0
    assert instrument.first_observed_at_ms == 10
    assert instrument.last_observed_at_ms == 20
    assert restored.market("BTC").replay_quality == "GOLD"
    assert restored.hot_candidates(now_ms=31)[0].coin == "ETH"


def test_specialized_sources_are_capabilities_not_fake_coins() -> None:
    registry = UniversalMarketRegistry(native_venues={"bybit", "okx", "gate", "bitget"})

    registry.register_specialized_sources()

    assert "DERIBIT" not in registry.coins
    assert registry.specialized_sources["deribit"] in {
        AvailabilityStatus.SPECIALIZED,
        AvailabilityStatus.REQUIRES_KEY,
    }


def test_historical_hub_capabilities_mark_instrument_without_downloading() -> None:
    hub = HistoricalBackfillHub(build_official_adapters(fetch_json=lambda *_args, **_kwargs: []).values())
    registry = UniversalMarketRegistry()
    registry.register(
        "BTC",
        "binance",
        "BTCUSDT",
        discovery=True,
        settle="USDT",
    )
    request = BackfillRequest(
        venue="binance",
        canonical_coin="BTC",
        exchange_symbol="BTCUSDT",
        data_type=HistoricalDataType.BBO,
        start_timestamp=1,
        end_timestamp=2,
    )

    registry.ingest_historical_capabilities(hub, [request])

    instrument = registry.market("BTC").instruments_for_venue("binance")[0]
    assert len(registry.market("BTC").instruments) == 1
    assert instrument.historical is True
    assert instrument.status is AvailabilityStatus.HISTORICAL_ONLY


def test_registry_scores_hot_candidates_from_real_coverage() -> None:
    registry = UniversalMarketRegistry(native_venues={"bybit", "gate", "bitget"})
    for venue in ("bybit", "gate", "bitget"):
        registry.register("XYZ", venue, f"XYZ-{venue}", native=True, historical=venue != "gate")
    registry.update_metrics("XYZ", volume_24h=2_000_000, open_interest=500_000, liquidity=100_000)

    candidate = registry.candidates(min_native_venues=2)[0]
    assert candidate.coin == "XYZ"
    assert candidate.score > 0
    assert candidate.hot_path_eligible is True


def test_registry_detects_all_listing_transitions_and_hot_queue() -> None:
    registry = UniversalMarketRegistry(native_venues={"gate"}, hot_candidate_hours=72)
    first = [{"coin": "BTC", "venue": "gate", "symbol": "BTC_USDT", "perpetual": True, "active": True}]
    events = registry.apply_snapshot(first, observed_at_ms=1_000)
    assert {event.event_type for event in events} == {
        DiscoveryEventType.NEW_MARKET,
        DiscoveryEventType.NEW_PERP,
    }
    registry.apply_snapshot([], observed_at_ms=2_000)
    events = registry.apply_snapshot(first, observed_at_ms=3_000)
    assert DiscoveryEventType.REACTIVATED in {event.event_type for event in events}
    assert registry.hot_candidates(now_ms=3_001)[0].expires_at_ms == 3_000 + 72 * 3_600_000


def test_gate_contract_and_sequenced_book_normalization() -> None:
    rows = parse_gate_contracts([{"name": "BTC_USDT", "in_delisting": False}])
    assert rows == [("BTC", "BTC_USDT")]
    state = GateMarketState(contract="BTC_USDT", stale_after_ms=1_000)
    state.apply_book({"t": 1000, "U": 1, "u": 1, "b": [[100, 2]], "a": [[101, 3]]}, receive_ts_ms=1_010)
    state.apply_book({"t": 1010, "U": 2, "u": 2, "b": [[100.5, 1]], "a": []}, receive_ts_ms=1_020)
    state.apply_ticker(
        {
            "contract": "BTC_USDT",
            "mark_price": "100.7",
            "index_price": "100.6",
            "funding_rate": "0.0001",
            "volume_24h_base": "50",
            "total_size": "25",
        }
    )
    snapshot = state.snapshot(now_ms=1_025)
    assert (snapshot.venue, snapshot.bid, snapshot.ask, snapshot.sequence) == ("gate", 100.5, 101.0, 2)
    assert snapshot.mark == 100.7
    assert snapshot.open_interest == 25.0


def test_gate_sequence_gap_fails_closed() -> None:
    state = GateMarketState(contract="BTC_USDT")
    state.apply_book({"t": 1000, "U": 1, "u": 1, "b": [[100, 2]], "a": [[101, 3]]}, receive_ts_ms=1_000)
    assert state.apply_book({"t": 1010, "U": 3, "u": 3, "b": [], "a": []}, receive_ts_ms=1_010) == "DESYNC"


def test_bitget_instrument_and_book_normalization() -> None:
    payload = {
        "data": [{"symbol": "ETHUSDT", "baseCoin": "ETH", "quoteCoin": "USDT", "symbolStatus": "normal"}]
    }
    assert parse_bitget_instruments(payload) == [("ETH", "ETHUSDT")]
    state = BitgetMarketState(symbol="ETHUSDT", stale_after_ms=1_000)
    state.apply(
        {
            "arg": {"channel": "books", "instId": "ETHUSDT"},
            "action": "snapshot",
            "data": [{"ts": "1000", "seq": "10", "bids": [[10, 4]], "asks": [[11, 5]]}],
        },
        receive_ts_ms=1_010,
    )
    state.apply(
        {
            "arg": {"channel": "ticker", "instId": "ETHUSDT"},
            "data": [
                {
                    "ts": "1010",
                    "markPrice": "10.5",
                    "indexPrice": "10.4",
                    "fundingRate": "0.0002",
                    "holdingAmount": "12",
                }
            ],
        },
        receive_ts_ms=1_020,
    )
    snapshot = state.snapshot(now_ms=1_025)
    assert (snapshot.venue, snapshot.bid, snapshot.ask, snapshot.sequence) == ("bitget", 10.0, 11.0, 10)
    assert snapshot.funding_rate == 0.0002


def test_bitget_crossed_book_fails_closed() -> None:
    state = BitgetMarketState(symbol="ETHUSDT")
    result = state.apply(
        {
            "arg": {"channel": "books", "instId": "ETHUSDT"},
            "action": "snapshot",
            "data": [{"ts": "1000", "seq": "1", "bids": [[12, 1]], "asks": [[11, 1]]}],
        },
        receive_ts_ms=1_000,
    )
    assert result == "UNMEASURABLE"


def _record(data_type: HistoricalDataType, ts: int, **payload) -> HistoricalRecord:
    receive_timestamp = payload.pop("receive_timestamp", None)
    sequence = payload.pop("sequence", None)
    event_id = payload.pop("event_id", None)
    return HistoricalRecord(
        venue="binance",
        canonical_coin="BTC",
        exchange_symbol="BTCUSDT",
        data_type=data_type,
        exchange_timestamp=ts,
        receive_timestamp=receive_timestamp,
        source="local",
        provenance="fixture",
        normalized=True,
        sequence=sequence,
        event_id=event_id,
        payload=payload,
    )


def test_local_jsonl_backfill_is_bounded_and_normalized(tmp_path) -> None:
    path = tmp_path / "trades.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [{"ts": 1, "price": 10}, {"ts": 2, "price": 11}, {"ts": 9, "price": 12}]
        ),
        encoding="utf-8",
    )
    hub = HistoricalBackfillHub()
    hub.register(LocalFileAdapter("local", path, field_map={"timestamp": "ts"}))
    result = hub.backfill(
        BackfillRequest(
            venue="binance",
            canonical_coin="BTC",
            exchange_symbol="BTCUSDT",
            data_type=HistoricalDataType.TRADES,
            start_timestamp=1,
            end_timestamp=3,
            limit=10,
            adapter="local",
        )
    )
    assert [record.exchange_timestamp for record in result.records] == [1, 2]


def test_tardis_import_is_optional_and_preserves_timestamps(tmp_path) -> None:
    path = tmp_path / "tardis.jsonl"
    path.write_text(
        json.dumps(
            {
                "exchange": "okex-futures",
                "symbol": "BTC-USDT-SWAP",
                "type": "book_snapshot_5",
                "timestamp": "2026-01-01T00:00:00Z",
                "local_timestamp": "2026-01-01T00:00:00.010Z",
                "bids": [[100, 1]],
                "asks": [[101, 1]],
            }
        ),
        encoding="utf-8",
    )
    hub = HistoricalBackfillHub([TardisFileAdapter(path)])
    result = hub.backfill(
        BackfillRequest(
            venue="okx",
            canonical_coin="BTC",
            exchange_symbol="BTC-USDT-SWAP",
            data_type=HistoricalDataType.BBO,
            start_timestamp=0,
            end_timestamp=9_999_999_999_999,
            adapter="tardis",
        )
    )
    assert result.records[0].source == "TARDIS"
    assert result.records[0].receive_timestamp > result.records[0].exchange_timestamp


def test_official_adapters_expose_honest_capabilities() -> None:
    adapters = build_official_adapters(fetch_json=lambda *_args, **_kwargs: [])
    assert HistoricalDataType.TRADES in adapters["binance"].capabilities
    assert HistoricalDataType.ORDER_BOOK_L2 in adapters["okx"].capabilities
    assert HistoricalDataType.LIQUIDATIONS not in adapters["bitget"].capabilities


def test_broken_historical_source_does_not_break_batch() -> None:
    class Broken:
        name = "broken"
        capabilities = frozenset({HistoricalDataType.TRADES})

        def fetch(self, request):
            raise RuntimeError("offline")

    hub = HistoricalBackfillHub([Broken()])
    results = hub.backfill_many(
        [
            BackfillRequest(
                venue="x",
                canonical_coin="BTC",
                exchange_symbol="BTC",
                data_type=HistoricalDataType.TRADES,
                start_timestamp=1,
                end_timestamp=2,
                adapter="broken",
            )
        ]
    )
    assert results[0].status == "ERROR"
    assert results[0].records == ()


@pytest.mark.parametrize(
    ("types", "expected"),
    [
        ({HistoricalDataType.OHLCV, HistoricalDataType.FUNDING}, ReplayQuality.BRONZE),
        (
            {
                HistoricalDataType.TRADES,
                HistoricalDataType.BBO,
                HistoricalDataType.FUNDING,
                HistoricalDataType.OPEN_INTEREST,
            },
            ReplayQuality.SILVER,
        ),
        (
            {
                HistoricalDataType.TRADES,
                HistoricalDataType.BBO,
                HistoricalDataType.ORDER_BOOK_L2,
                HistoricalDataType.FUNDING,
                HistoricalDataType.OPEN_INTEREST,
                HistoricalDataType.MARK_PRICE,
                HistoricalDataType.INDEX_PRICE,
                HistoricalDataType.LIQUIDATIONS,
            },
            ReplayQuality.GOLD,
        ),
    ],
)
def test_replay_quality_levels(types, expected) -> None:
    records = [
        _record(data_type, index + 1, sequence=index + 1, receive_timestamp=index + 2)
        for index, data_type in enumerate(types)
    ]
    assert determine_replay_quality(records) is expected


def test_gold_requires_sequence_and_exchange_timestamp() -> None:
    types = {
        HistoricalDataType.TRADES,
        HistoricalDataType.BBO,
        HistoricalDataType.ORDER_BOOK_L2,
        HistoricalDataType.FUNDING,
        HistoricalDataType.OPEN_INTEREST,
        HistoricalDataType.MARK_PRICE,
        HistoricalDataType.INDEX_PRICE,
        HistoricalDataType.LIQUIDATIONS,
    }
    records = [_record(data_type, index + 1) for index, data_type in enumerate(types)]
    assert determine_replay_quality(records) is ReplayQuality.SILVER


def test_point_in_time_orders_by_known_at_and_excludes_future_information() -> None:
    records = [
        _record(HistoricalDataType.TRADES, 100, receive_timestamp=120),
        _record(HistoricalDataType.BBO, 90, receive_timestamp=95),
        _record(HistoricalDataType.FUNDING, 80, receive_timestamp=130),
    ]
    timeline = order_point_in_time(records, decision_timestamp=125)
    assert [(row.data_type, row.known_at) for row in timeline] == [
        (HistoricalDataType.BBO, 95),
        (HistoricalDataType.TRADES, 120),
    ]


def test_historical_quality_rejects_missing_timestamp_duplicate_and_negative() -> None:
    missing = _record(HistoricalDataType.TRADES, 0)
    duplicate = _record(HistoricalDataType.BBO, 10, bid=10, ask=11, event_id="same")
    bad = _record(HistoricalDataType.BBO, 11, bid=-1, ask=10)
    verdict = validate_historical_record(missing)
    assert verdict.accepted is False and "MISSING_TIMESTAMP" in verdict.reasons
    assert validate_historical_record(bad).accepted is False
    assert order_point_in_time([duplicate, duplicate], decision_timestamp=20) == [duplicate]
