from __future__ import annotations

import asyncio
import copy
import gzip
import json

import httpx

from hl_observer.collection.bitget_market_data import BitgetMarketState
from hl_observer.collection.depth_capacity import (
    build_capacity_tape,
    build_cross_venue_capacity_tape,
    capacity_tape_envelope,
)
from hl_observer.collection.gate_market_data import GateMarketState
from hl_observer.collection.native_funding_history import (
    fetch_bitget_funding_settlements,
    fetch_gate_funding_settlements,
)
from hl_observer.collection.native_market_tape import native_tick_envelope
from hl_observer.collection.native_venue_market import DESYNC
from hl_observer.collection.trade_reconciliation import (
    reconcile_bitget_trade_shard,
    reconcile_gate_trade_shard,
)
from tools.collect_cloud_window import (
    _binance_liquidation_envelope,
    _capacity_size_multiplier_from_metadata,
    _replay_grade_coverage_report,
)


def _transport() -> dict:
    return {
        "connection_id": "test-conn",
        "receive_wall_ts_ms": 2_000,
        "receive_mono_ns": 123_456,
        "transport_rtt_ms": 8.0,
        "clock_offset_ms": -2.0,
    }


def test_gate_rich_public_channels_are_taped() -> None:
    common = {"_alina_transport": _transport()}
    cases = [
        (
            {"channel": "futures.book_ticker", "event": "update", "result": {"s": "BTC_USDT", "b": "100", "a": "101", "t": 1995}, **common},
            "bbo",
        ),
        (
            {"channel": "futures.trades", "event": "update", "result": [{"id": 42, "contract": "BTC_USDT", "create_time_ms": 1995, "price": "100", "size": 1}], **common},
            "trades",
        ),
        (
            {"channel": "futures.tickers", "event": "update", "result": [{"contract": "BTC_USDT", "last": "100", "mark_price": "100.1"}], **common},
            "ticker",
        ),
        (
            {"channel": "futures.contract_stats", "event": "update", "result": [{"contract": "BTC_USDT", "time_ms": 1995, "open_interest": "50"}], **common},
            "open_interest",
        ),
        (
            {"channel": "futures.public_liquidates", "event": "update", "result": [{"contract": "BTC_USDT", "time_ms": 1995, "price": "99", "size": "-2"}], **common},
            "liquidations",
        ),
    ]
    for payload, family in cases:
        envelope = native_tick_envelope("gate", payload)
        assert envelope is not None
        assert envelope.channel == family
        assert envelope.instrument == "BTC_USDT"


def test_bitget_bbo_liquidation_and_vwap_depth_evidence() -> None:
    bbo = native_tick_envelope(
        "bitget",
        {
            "arg": {"instType": "USDT-FUTURES", "channel": "books1", "instId": "BTCUSDT"},
            "data": [{"ts": "1995", "seq": "10", "bids": [["100", "2"]], "asks": [["101", "2"]]}],
            "_alina_transport": _transport(),
        },
    )
    assert bbo is not None
    assert bbo.channel == "bbo"
    assert bbo.parsed_summary["depth_curve_replay_ready"] is True
    assert bbo.parsed_summary["vwap_target_quote_notionals_usd"] == [10, 25, 50, 100, 250, 500, 1000]

    liquidation = native_tick_envelope(
        "bitget",
        {
            "arg": {"instType": "USDT-FUTURES", "channel": "liquidation", "instId": "BTCUSDT"},
            "data": [{"symbol": "BTCUSDT", "side": "sell", "price": "99", "amount": "2", "ts": "1995"}],
            "_alina_transport": _transport(),
        },
    )
    assert liquidation is not None
    assert liquidation.channel == "liquidations"


def test_gate_and_bitget_gap_detection_is_fail_closed() -> None:
    gate = GateMarketState("BTC_USDT")
    gate.apply_book({"U": 10, "u": 10, "b": [["100", "1"]], "a": [["101", "1"]]}, receive_ts_ms=1000)
    assert gate.apply_book({"U": 12, "u": 12, "b": [["100", "2"]], "a": []}, receive_ts_ms=1010) == DESYNC
    assert gate.gap_count == 1

    bitget = BitgetMarketState("BTCUSDT")
    bitget.apply(
        {"arg": {"channel": "books", "instId": "BTCUSDT"}, "data": [{"seq": "10", "bids": [["100", "1"]], "asks": [["101", "1"]]}]},
        receive_ts_ms=1000,
    )
    assert bitget.apply(
        {"arg": {"channel": "books", "instId": "BTCUSDT"}, "data": [{"seq": "12", "pseq": "9", "bids": [["100", "2"]], "asks": []}]},
        receive_ts_ms=1010,
    ) == DESYNC
    assert bitget.gap_count == 1


def test_gate_and_bitget_funding_history_are_bounded() -> None:
    async def scenario() -> None:
        async def gate_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"t": 2, "r": "0.0001"}, {"t": 9, "r": "0.0002"}])

        gate_client = httpx.AsyncClient(
            base_url="https://api.gateio.ws/api/v4",
            transport=httpx.MockTransport(gate_handler),
        )
        gate_rows = await fetch_gate_funding_settlements(
            ["BTC_USDT"], start_ms=1000, end_ms=5000, http_client=gate_client
        )
        await gate_client.aclose()
        assert [row.exchange_ts_ms for row in gate_rows] == [2000]

        async def bitget_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "code": "00000",
                    "data": [
                        {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingTime": "2000"},
                        {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingTime": "9000"},
                    ],
                },
            )

        bitget_client = httpx.AsyncClient(
            base_url="https://api.bitget.com",
            transport=httpx.MockTransport(bitget_handler),
        )
        bitget_rows = await fetch_bitget_funding_settlements(
            ["BTCUSDT"], start_ms=1000, end_ms=5000, http_client=bitget_client
        )
        await bitget_client.aclose()
        assert [row.exchange_ts_ms for row in bitget_rows] == [2000]

    asyncio.run(scenario())


def test_gate_and_bitget_exact_trade_reconciliation(tmp_path) -> None:
    gate_path = tmp_path / "gate.jsonl.gz"
    with gzip.open(gate_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": {"channel": "futures.trades", "result": [{"id": 7, "contract": "BTC_USDT", "create_time_ms": 1000}]}}) + "\n")
    bitget_path = tmp_path / "bitget.jsonl.gz"
    with gzip.open(bitget_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": {"arg": {"channel": "trade", "instId": "BTCUSDT"}, "data": [{"tradeId": "8", "ts": "1000"}]}}) + "\n")

    async def scenario() -> None:
        async def gate_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": 7, "contract": "BTC_USDT", "create_time_ms": 1000}])
        gate_client = httpx.AsyncClient(base_url="https://api.gateio.ws/api/v4", transport=httpx.MockTransport(gate_handler))
        gate_report = await reconcile_gate_trade_shard(
            gate_path, symbol="BTC_USDT", start_ms=1000, end_ms=1100, client=gate_client
        )
        await gate_client.aclose()
        assert gate_report["status"] == "MATCHED"

        async def bitget_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": "00000", "data": [{"tradeId": "8", "ts": "1000"}]})
        bitget_client = httpx.AsyncClient(base_url="https://api.bitget.com", transport=httpx.MockTransport(bitget_handler))
        bitget_report = await reconcile_bitget_trade_shard(
            bitget_path, symbol="BTCUSDT", start_ms=1000, end_ms=1100, client=bitget_client
        )
        await bitget_client.aclose()
        assert bitget_report["status"] == "MATCHED"

    asyncio.run(scenario())


def test_gate_and_bitget_reconciliation_use_live_exchange_time_bounds(tmp_path) -> None:
    gate_path = tmp_path / "gate-bounds.jsonl.gz"
    with gzip.open(gate_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": {"result": [
            {"id": 7, "create_time_ms": 1050}, {"id": 8, "create_time_ms": 1080}
        ]}}) + "\n")
    bitget_path = tmp_path / "bitget-bounds.jsonl.gz"
    with gzip.open(bitget_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": {"data": [
            {"tradeId": "7", "ts": "1050"}, {"tradeId": "8", "ts": "1080"}
        ]}}) + "\n")

    async def scenario() -> None:
        async def gate_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[
                {"id": 6, "create_time_ms": 1005}, {"id": 7, "create_time_ms": 1050},
                {"id": 8, "create_time_ms": 1080}, {"id": 9, "create_time_ms": 1095},
            ])
        gate_client = httpx.AsyncClient(base_url="https://api.gateio.ws/api/v4", transport=httpx.MockTransport(gate_handler))
        gate_report = await reconcile_gate_trade_shard(gate_path, symbol="BTC_USDT", start_ms=1000, end_ms=1100, client=gate_client)
        await gate_client.aclose()
        assert gate_report["status"] == "MATCHED"

        async def bitget_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": "00000", "data": [
                {"tradeId": "9", "ts": "1095"}, {"tradeId": "8", "ts": "1080"},
                {"tradeId": "7", "ts": "1050"}, {"tradeId": "6", "ts": "1005"},
            ]})
        bitget_client = httpx.AsyncClient(base_url="https://api.bitget.com", transport=httpx.MockTransport(bitget_handler))
        bitget_report = await reconcile_bitget_trade_shard(bitget_path, symbol="BTCUSDT", start_ms=1000, end_ms=1100, client=bitget_client)
        await bitget_client.aclose()
        assert bitget_report["status"] == "MATCHED"

    asyncio.run(scenario())


def test_replay_grade_coverage_uses_actual_published_families() -> None:
    manifests = []
    for family in ("l2Book", "bbo", "trades", "ticker", "capacity_tape", "instrument_metadata"):
        manifests.append(
            {
                "venue": "bitget",
                "symbol": "BTCUSDT",
                "family": family,
                "event_count": 1,
                "integrity": {
                    "missing_monotonic_count": 0,
                    "missing_timestamp_count": 0,
                    "gap_count": 0,
                    "regression_count": 0,
                },
                "reconciliation": (
                    {"status": "MATCHED"} if family == "trades" else {"status": "UNVERIFIED"}
                ),
            }
        )
    manifests.append(
        {
            "venue": "bitget",
            "symbol": "__VENUE__",
            "family": "clock_sync",
            "event_count": 1,
            "integrity": {},
        }
    )
    report = _replay_grade_coverage_report(manifests, {"bitget": ["BTCUSDT"]})
    assert report["complete"] is True
    broken = [row for row in manifests if row["family"] != "bbo"]
    report = _replay_grade_coverage_report(broken, {"bitget": ["BTCUSDT"]})
    assert report["complete"] is False
    assert report["per_venue"]["bitget"]["missing_families_by_symbol"]["BTCUSDT"] == ["bbo"]

    unreconciled = [
        {**row, "reconciliation": {"status": "PARTIAL"}}
        if row["family"] == "trades"
        else row
        for row in manifests
    ]
    report = _replay_grade_coverage_report(unreconciled, {"bitget": ["BTCUSDT"]})
    assert report["complete"] is False
    assert report["per_venue"]["bitget"]["trade_reconciliation_defects_by_symbol"]["BTCUSDT"] == ["PARTIAL"]


def test_binance_public_liquidation_is_taped() -> None:
    envelope = _binance_liquidation_envelope(
        {
            "data": {
                "e": "forceOrder",
                "E": 2_000,
                "o": {
                    "s": "BTCUSDT",
                    "S": "SELL",
                    "T": 1_995,
                    "ap": "65000",
                    "z": "0.25",
                },
            }
        },
        received_ts_ms=2_005,
        receive_mono_ns=456_789,
        connection_id="binance-liquidation-test",
        clock_evidence={
            "clock_offset_ms": -2.0,
            "clock_probe_rtt_ms": 8.0,
        },
    )
    assert envelope is not None
    assert envelope.channel == "liquidations"
    assert envelope.instrument == "BTCUSDT"
    assert envelope.exchange_ts_ms == 1_995
    assert envelope.local_monotonic_ns == 456_789
    assert envelope.parsed_summary["price"] == 65000.0
    assert envelope.parsed_summary["size"] == 0.25
    assert envelope.parsed_summary["clock_offset_ms"] == -2.0


def test_gate_and_bitget_ticker_context_is_normalized() -> None:
    gate = native_tick_envelope(
        "gate",
        {
            "channel": "futures.tickers",
            "event": "update",
            "time_ms": 2_000,
            "result": [{
                "contract": "BTC_USDT",
                "last": "100",
                "mark_price": "100.1",
                "index_price": "99.9",
                "funding_rate": "0.0001",
                "total_size": "123.5",
                "volume_24h_base": "456",
                "volume_24h_quote": "45600",
                "t": 1_995,
            }],
            "_alina_transport": _transport(),
        },
    )
    assert gate is not None
    assert gate.parsed_summary["mark_price"] == 100.1
    assert gate.parsed_summary["index_price"] == 99.9
    assert gate.parsed_summary["funding_rate"] == 0.0001
    assert gate.parsed_summary["open_interest"] == 123.5

    bitget = native_tick_envelope(
        "bitget",
        {
            "arg": {"instType": "USDT-FUTURES", "channel": "ticker", "instId": "BTCUSDT"},
            "data": [{
                "lastPr": "100",
                "bidPr": "99.9",
                "askPr": "100.1",
                "markPrice": "100.05",
                "indexPrice": "99.95",
                "fundingRate": "0.0002",
                "holdingAmount": "456.5",
                "baseVolume": "1000",
                "quoteVolume": "100000",
                "nextFundingTime": "3000",
                "ts": "1995",
            }],
            "_alina_transport": _transport(),
        },
    )
    assert bitget is not None
    assert bitget.parsed_summary["mark_price"] == 100.05
    assert bitget.parsed_summary["index_price"] == 99.95
    assert bitget.parsed_summary["funding_rate"] == 0.0002
    assert bitget.parsed_summary["open_interest"] == 456.5


def test_gate_contract_info_change_is_replayable() -> None:
    envelope = native_tick_envelope(
        "gate",
        {
            "channel": "futures.contract_info",
            "event": "update",
            "time_ms": 1_995,
            "result": {
                "contract": "BTC_USDT",
                "order_price_round": "0.1",
                "quanto_multiplier": "0.001",
                "order_size_min": "1",
            },
            "_alina_transport": _transport(),
        },
    )
    assert envelope is not None
    assert envelope.channel == "instrument_metadata"
    assert envelope.instrument == "BTC_USDT"
    assert envelope.parsed_summary["tick_size"] == "0.1"
    assert envelope.parsed_summary["contract_multiplier"] == "0.001"



def test_capacity_tape_walks_reconstructed_depth_at_predeclared_notionals() -> None:
    tape = build_capacity_tape(
        bids=[[100, 1], [99, 2]],
        asks=[[101, 1], [102, 2]],
        exchange_ts_ms=1_990,
        receive_ts_ms=2_000,
        sequence=42,
    )
    assert tape["target_notionals_usd"] == [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
    assert tape["book_age_ms"] == 10
    assert tape["source_sequence"] == 42
    assert tape["buy_from_asks"][3]["fully_fillable"] is True
    assert tape["buy_from_asks"][-1]["fully_fillable"] is False
    assert 0.0 < tape["buy_from_asks"][-1]["fill_ratio"] < 1.0
    assert tape["buy_from_asks"][3]["executable_vwap"] == 101.0
    assert tape["buy_from_asks"][4]["side"] == "BUY"
    assert tape["buy_from_asks"][4]["levels_consumed"] == 2
    assert tape["buy_from_asks"][4]["worst_consumed_price"] == 102.0
    assert tape["buy_from_asks"][4]["requested_notional_usd"] == 250.0
    assert tape["buy_from_asks"][4]["cumulative_depth_base_qty"] > 2.0
    assert tape["buy_from_asks"][4]["quality_status"] == "CERTIFIABLE"
    assert tape["buy_from_asks"][-1]["quality_status"] == "UNMEASURABLE"
    assert tape["buy_from_asks"][-1]["failure_reason"] == "INSUFFICIENT_DEPTH"


def test_capacity_tape_exact_vwap_sides_and_slippage() -> None:
    tape = build_capacity_tape(
        bids=[[99, 1], [98, 1]],
        asks=[[101, 1], [102, 1]],
        notionals_usd=[150],
    )
    buy = tape["buy_from_asks"][0]
    sell = tape["sell_into_bids"][0]
    assert buy == {
        "side": "BUY",
        "target_notional_usd": 150.0,
        "requested_notional_usd": 150.0,
        "filled_notional_usd": 150.0,
        "fill_ratio": 1.0,
        "base_qty": 1.4803921569,
        "cumulative_depth_base_qty": 1.4803921569,
        "executable_vwap": 101.3245033113,
        "worst_consumed_price": 102.0,
        "spread_cost_bps": 132.4503311258,
        "incremental_depth_slippage_bps": 32.1290407186,
        "cumulative_consumed_notional_usd": 150.0,
        "levels_consumed": 2,
        "fully_fillable": True,
        "quality_status": "CERTIFIABLE",
        "failure_reason": None,
    }
    assert sell["side"] == "SELL"
    assert sell["executable_vwap"] == 98.6577181208
    assert sell["worst_consumed_price"] == 98.0
    assert sell["spread_cost_bps"] == 134.2281879195
    assert sell["incremental_depth_slippage_bps"] == 34.5739271914
    assert sell["levels_consumed"] == 2


def test_capacity_tape_preserves_provenance_and_does_not_mutate_raw_l2() -> None:
    raw = {
        "topic": "orderbook.200.BTCUSDT",
        "type": "snapshot",
        "data": {"s": "BTCUSDT", "b": [["100", "1"]], "a": [["101", "1"]], "u": 7},
    }
    before = copy.deepcopy(raw)
    envelope = capacity_tape_envelope(
        venue="bybit",
        instrument="BTCUSDT",
        bids=[[100, 1]],
        asks=[[101, 1]],
        exchange_ts_ms=1_990,
        received_ts_ms=2_000,
        receive_mono_ns=123,
        connection_id="c1",
        sequence=10,
        snapshot_id=7,
        quality="EXPLOITABLE",
        timing_evidence={"transport_rtt_ms": 4.0, "uncertainty_ms": 2.0},
        source_raw_l2_payload=raw,
    )
    assert envelope is not None
    assert raw == before
    summary = envelope.parsed_summary
    assert summary["venue"] == "bybit"
    assert summary["instrument"] == "BTCUSDT"
    assert summary["coin"] == "BTC"
    assert summary["receive_wall_ts_ms"] == 2_000
    assert summary["receive_monotonic_ns"] == 123
    assert summary["exchange_ts_ms"] == 1_990
    assert summary["source_sequence"] == 10
    assert summary["source_snapshot_id"] == 7
    assert len(summary["source_raw_l2_sha256"]) == 64
    assert len(summary["source_reconstructed_book_sha256"]) == 64
    assert summary["transport_rtt_ms"] == 4.0
    assert summary["timing_uncertainty_ms"] == 2.0
    assert envelope.provenance["source_raw_l2_sha256"] == summary["source_raw_l2_sha256"]


def test_capacity_tape_envelope_fails_closed_on_desync() -> None:
    envelope = capacity_tape_envelope(
        venue="bitget",
        instrument="BTCUSDT",
        bids=[[100, 1]],
        asks=[[101, 1]],
        exchange_ts_ms=1_990,
        received_ts_ms=2_000,
        receive_mono_ns=123,
        connection_id="c1",
        sequence=10,
        quality="DESYNC",
    )
    assert envelope is None

    envelope = capacity_tape_envelope(
        venue="bitget",
        instrument="BTCUSDT",
        bids=[[100, 1]],
        asks=[[101, 1]],
        exchange_ts_ms=1_990,
        received_ts_ms=2_000,
        receive_mono_ns=123,
        connection_id="c1",
        sequence=10,
        quality="EXPLOITABLE",
        timing_evidence={"clock_offset_ms": -2.0, "clock_probe_rtt_ms": 8.0},
    )
    assert envelope is not None
    assert envelope.channel == "capacity_tape"
    assert envelope.parsed_summary["raw_l2_source_of_truth"] is True
    assert envelope.parsed_summary["clock_offset_ms"] == -2.0



def test_capacity_multiplier_rules_are_explicit() -> None:
    assert _capacity_size_multiplier_from_metadata(
        "gate",
        "BTC_USDT",
        {"quanto_multiplier": "0.001"},
    ) == 0.001
    assert _capacity_size_multiplier_from_metadata(
        "okx",
        "BTC-USDT-SWAP",
        {"ctVal": "0.01", "ctValCcy": "BTC"},
    ) == 0.01
    assert _capacity_size_multiplier_from_metadata(
        "okx",
        "BTC-USDT-SWAP",
        {"ctVal": "0.01", "ctValCcy": "USDT"},
    ) is None
    assert _capacity_size_multiplier_from_metadata(
        "bitget",
        "BTCUSDT",
        {"sizeMultiplier": "0.001"},
    ) == 1.0

    tape = build_capacity_tape(
        bids=[[100, 10]],
        asks=[[101, 10]],
        notionals_usd=[1.0],
        exchange_ts_ms=1_990,
        receive_ts_ms=2_000,
        size_multiplier_to_base=0.001,
    )
    assert tape["size_multiplier_to_base"] == 0.001
    assert tape["bid_available_notional_usd"] == 1.0
    assert tape["ask_available_notional_usd"] == 1.01
    assert tape["sell_into_bids"][0]["fully_fillable"] is True


def test_capacity_tape_fails_closed_without_contract_multiplier() -> None:
    envelope = capacity_tape_envelope(
        venue="gate",
        instrument="BTC_USDT",
        bids=[[100, 10]],
        asks=[[101, 10]],
        exchange_ts_ms=1_990,
        received_ts_ms=2_000,
        receive_mono_ns=123,
        connection_id="gate-test",
        sequence=10,
        quality="EXPLOITABLE",
        size_multiplier_to_base=None,
    )
    assert envelope is None


def test_replay_grade_coverage_rejects_capacity_integrity_defects() -> None:
    manifests = []
    for family in ("l2Book", "bbo", "trades", "ticker", "capacity_tape", "instrument_metadata"):
        manifests.append(
            {
                "venue": "bitget",
                "symbol": "BTCUSDT",
                "family": family,
                "event_count": 1,
                "integrity": {
                    "missing_monotonic_count": 0,
                    "missing_timestamp_count": 0,
                    "gap_count": 1 if family == "capacity_tape" else 0,
                    "regression_count": 0,
                },
                "reconciliation": {"status": "MATCHED" if family == "trades" else "UNVERIFIED"},
            }
        )
    manifests.append({"venue": "bitget", "symbol": "__VENUE__", "family": "clock_sync", "event_count": 1, "integrity": {}})
    report = _replay_grade_coverage_report(manifests, {"bitget": ["BTCUSDT"]})
    assert report["complete"] is False
    assert report["per_venue"]["bitget"]["timing_defects_by_symbol"]["BTCUSDT"] == ["GAP"]


def test_cross_venue_capacity_is_minimum_of_simultaneous_legs() -> None:
    left = build_capacity_tape(
        bids=[[99, 4]],
        asks=[[100, 3]],
        notionals_usd=[100, 250, 500],
        exchange_ts_ms=1_990,
        receive_ts_ms=2_000,
        sequence=10,
    )
    right = build_capacity_tape(
        bids=[[101, 2]],
        asks=[[102, 5]],
        notionals_usd=[100, 250, 500],
        exchange_ts_ms=1_992,
        receive_ts_ms=2_003,
        sequence=20,
    )
    tape = build_cross_venue_capacity_tape(
        venue_a="bybit",
        instrument_a="BTCUSDT",
        tape_a=left,
        receive_mono_ns_a=100,
        venue_b="okx",
        instrument_b="BTC-USDT-SWAP",
        tape_b=right,
        receive_mono_ns_b=103,
    )
    assert tape is not None
    assert tape["coin"] == "BTC"
    assert tape["receive_skew_ns"] == 3
    forward = tape["directions"]["BUY_A_SELL_B"]
    assert forward["entry_capacity_leg_a_usd"] == 300.0
    assert forward["entry_capacity_leg_b_usd"] == 202.0
    assert forward["entry_simultaneous_capacity_usd"] == 202.0
    assert forward["exit_capacity_leg_a_usd"] == 396.0
    assert forward["exit_capacity_leg_b_usd"] == 510.0
    assert forward["exit_simultaneous_capacity_usd"] == 396.0
    assert forward["target_rows"][-1]["entry_quality_status"] == "UNMEASURABLE"
    assert tape["paper_read_only"] is True
    assert tape["real_execution"] is False


def test_replay_grade_requires_published_cross_venue_capacity_for_shared_coin() -> None:
    required = {
        "bybit": ("l2Book", "bbo", "trades", "ticker", "capacity_tape", "instrument_metadata"),
        "okx": ("l2Book", "bbo", "trades", "ticker", "capacity_tape", "instrument_metadata"),
    }
    manifests = []
    for venue, families in required.items():
        symbol = "BTCUSDT" if venue == "bybit" else "BTC-USDT-SWAP"
        for family in families:
            manifests.append(
                {
                    "venue": venue,
                    "symbol": symbol,
                    "family": family,
                    "event_count": 1,
                    "integrity": {"missing_monotonic_count": 0, "missing_timestamp_count": 0, "gap_count": 0, "regression_count": 0},
                    "reconciliation": {"status": "MATCHED" if family == "trades" else "UNVERIFIED"},
                }
            )
        manifests.append({"venue": venue, "symbol": "__VENUE__", "family": "clock_sync", "event_count": 1, "integrity": {}})
    report = _replay_grade_coverage_report(
        manifests,
        {"bybit": ["BTCUSDT"], "okx": ["BTC-USDT-SWAP"]},
    )
    assert report["complete"] is False
    assert report["missing_cross_venue_capacity_coins"] == ["BTC"]

    manifests.append(
        {
            "venue": "unknown",
            "symbol": "BTC",
            "family": "cross_venue_capacity_tape",
            "event_count": 1,
            "integrity": {"missing_monotonic_count": 0, "missing_timestamp_count": 0, "gap_count": 0, "regression_count": 0},
        }
    )
    report = _replay_grade_coverage_report(
        manifests,
        {"bybit": ["BTCUSDT"], "okx": ["BTC-USDT-SWAP"]},
    )
    assert report["complete"] is True
    assert report["missing_cross_venue_capacity_coins"] == []
