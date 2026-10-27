from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from tools import collect_cloud_copy_vault as C


def test_l2_payload_classifier_reports_stable_rejection_reasons() -> None:
    valid = {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": 1_700_000_000_000,
            "levels": [
                [{"px": "100", "sz": "2", "n": 1}],
                [{"px": "101", "sz": "3", "n": 2}],
            ],
        },
    }
    cases = [
        ("{not-json", "invalid_json", None),
        (json.dumps({"channel": "pong"}), "wrong_channel", None),
        (json.dumps({"channel": "l2Book", "data": {"time": 1, "levels": [[], []]}}), "missing_coin", None),
        (json.dumps({"channel": "l2Book", "data": {"coin": "BTC", "time": 1, "levels": [[], {}]}}), "invalid_levels", "BTC"),
        (json.dumps({"channel": "l2Book", "data": {"coin": "BTC", "time": "bad", "levels": [[], []]}}), "invalid_timestamp", "BTC"),
        (json.dumps(["not", "an", "object"]), "other_schema", None),
    ]

    for raw, expected_reason, expected_coin in cases:
        _, reason, coin = C.classify_l2_payload(raw)
        assert reason == expected_reason
        assert coin == expected_coin

    parsed, reason, coin = C.classify_l2_payload(json.dumps(valid))
    assert reason is None
    assert coin == "BTC"
    assert parsed == valid


def test_l2_classifier_rejects_unsorted_duplicate_crossed_and_empty_books() -> None:
    valid_levels = [
        [
            {"px": "100", "sz": "2", "n": 1},
            {"px": "99", "sz": "3", "n": 1},
        ],
        [
            {"px": "101", "sz": "2", "n": 1},
            {"px": "102", "sz": "3", "n": 1},
        ],
    ]
    cases = []
    unsorted = json.loads(json.dumps(valid_levels))
    unsorted[0].reverse()
    cases.append(unsorted)
    duplicate = json.loads(json.dumps(valid_levels))
    duplicate[1][1]["px"] = duplicate[1][0]["px"]
    cases.append(duplicate)
    crossed = json.loads(json.dumps(valid_levels))
    crossed[1][0]["px"] = "99.5"
    cases.append(crossed)
    cases.append([[], valid_levels[1]])

    for levels in cases:
        _, reason, coin = C.classify_l2_payload(
            json.dumps(
                {
                    "channel": "l2Book",
                    "data": {
                        "coin": "BTC",
                        "time": 1_700_000_000_000,
                        "levels": levels,
                    },
                }
            )
        )
        assert reason == "invalid_levels"
        assert coin == "BTC"


def test_cloud_l2_path_preserves_case_sensitive_native_coin() -> None:
    message = {
        "channel": "l2Book",
        "data": {
            "coin": "kPEPE", "time": 1_700_000_000_000,
            "levels": [
                [{"px": "0.0001", "sz": "100", "n": 1}],
                [{"px": "0.0002", "sz": "100", "n": 1}],
            ],
        },
    }

    parsed, reason, coin = C.classify_l2_payload(json.dumps(message))
    envelope = C.l2_envelope(
        message,
        receive_wall_ms=1_700_000_000_001,
        receive_mono_ns=42,
        connection_id="case-sensitive-test",
    )

    assert reason is None and parsed == message and coin == "kPEPE"
    assert envelope is not None and envelope.instrument == "kPEPE"
    assert C._subscription_identity({"type": "l2Book", "coin": "kPEPE"}) == (
        "l2Book", "kPEPE",
    )


def test_copy_vault_market_envelopes_preserve_causal_feeds_and_native_instrument() -> None:
    trade = {
        "coin": "xyz:TSLA", "time": 2_002, "px": "100.5", "sz": "1",
        "side": "B", "hash": "0xtrade", "tid": 7,
    }
    envelopes = C.copy_vault_market_envelopes(
        {"channel": "trades", "data": [trade]},
        receive_wall_ms=2_010,
        receive_mono_ns=123,
        connection_id="market-test",
    )

    assert len(envelopes) == 1
    assert envelopes[0].instrument == "xyz:TSLA"
    assert envelopes[0].exchange_ts_ms == 2_002
    assert envelopes[0].provenance["timestamp_semantics"] == "causal_event_availability"
    assert envelopes[0].parsed_summary["data_gate_ready"] is False


def test_copy_vault_market_subscription_plan_keeps_native_symbol() -> None:
    subscriptions = C.copy_vault_market_subscriptions("xyz:TSLA")

    assert {row["type"] for row in subscriptions} == {
        "bbo", "l2Book", "trades", "activeAssetCtx",
    }
    assert {row["coin"] for row in subscriptions} == {"xyz:TSLA"}


def test_market_stream_data_is_admitted_only_after_connection_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ms = int(C.time.time() * 1_000)
    subscriptions = [
        {"type": kind, "coin": "BTC"}
        for kind in C.COPY_VAULT_MARKET_CHANNEL_TYPES
    ]
    messages: list[dict[str, object]] = [
        {
            "channel": "bbo",
            "data": {
                "coin": "BTC", "time": now_ms,
                "bbo": [{"px": "100", "sz": "1"}, {"px": "101", "sz": "2"}],
            },
        },  # rejected: no ACK on this connection yet
    ]
    messages.extend(
        {
            "channel": "subscriptionResponse",
            "data": {"method": "subscribe", "subscription": subscription},
        }
        for subscription in subscriptions
    )
    messages.extend([
        {
            "channel": "bbo",
            "data": {
                "coin": "BTC", "time": now_ms,
                "bbo": [{"px": "100", "sz": "1"}, {"px": "101", "sz": "2"}],
            },
        },
        {
            "channel": "trades",
            "data": [{
                "coin": "BTC", "time": now_ms, "px": "100.5", "sz": "0.2",
                "side": "B", "hash": "0xabc", "tid": 1,
            }],
        },
        {"channel": "activeAssetCtx", "data": {"coin": "BTC", "ctx": {"markPx": "100.5"}}},
        {
            "channel": "l2Book",
            "data": {
                "coin": "BTC", "time": now_ms,
                "levels": [[{"px": "100", "sz": "1", "n": 1}],
                           [{"px": "101", "sz": "1", "n": 1}]],
            },
        },
    ])

    class FakeSocket:
        def __init__(self) -> None:
            self.release = asyncio.Event()

        async def send(self, _payload: str) -> None:
            return None

        def __aiter__(self):
            async def iterate():
                for message in messages:
                    yield json.dumps(message)
                await self.release.wait()
            return iterate()

    class FakeConnection:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    socket = FakeSocket()
    monkeypatch.setattr(
        C.websockets, "connect", lambda *_args, **_kwargs: FakeConnection(socket)
    )

    class Sink:
        def __init__(self) -> None:
            self.envelopes: list[C.TickEnvelope] = []

        async def emit_async(self, envelope: C.TickEnvelope) -> None:
            self.envelopes.append(envelope)

    async def scenario() -> None:
        state = C.new_l2_state()
        sink = Sink()
        task = asyncio.create_task(
            C._dynamic_l2_collector(sink, asyncio.Queue(), {"BTC"}, state)
        )
        try:
            for _ in range(300):
                if len(sink.envelopes) >= 4:
                    break
                await asyncio.sleep(0.01)
            assert {row.channel for row in sink.envelopes} == {
                "copy_vault_l2", "copy_vault_bbo", "copy_vault_trades",
                "copy_vault_active_asset_ctx",
            }
            assert state["market_rejected_before_ack"] == 1
            assert state["market_acknowledged"] == 3
            assert state["market_accepted_by_channel"] == {
                "activeAssetCtx": 1, "bbo": 1, "trades": 1,
            }
        finally:
            socket.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_copy_vault_accounting_streams_preserve_funding_and_ledger_events() -> None:
    vault = "0x" + "a" * 40
    funding, funding_error = C.copy_vault_accounting_envelopes(
        {
            "channel": "userFundings",
            "data": {
                "user": vault, "isSnapshot": False,
                "fundings": [{
                    "time": 2_000, "coin": "kPEPE", "usdc": "-0.25",
                    "szi": "100", "fundingRate": "0.0001",
                }],
            },
        },
        vault=vault,
        receive_wall_ms=2_002,
        receive_mono_ns=10,
        connection_id="accounting-test",
    )
    ledger, ledger_error = C.copy_vault_accounting_envelopes(
        {
            "channel": "userNonFundingLedgerUpdates",
            "data": {
                "user": vault, "isSnapshot": False,
                "nonFundingLedgerUpdates": [{
                    "time": 2_001, "hash": "0xledger",
                    "delta": {"type": "deposit", "usdc": 10.0},
                }],
            },
        },
        vault=vault,
        receive_wall_ms=2_002,
        receive_mono_ns=11,
        connection_id="accounting-test",
    )

    assert funding_error is None and ledger_error is None
    assert len(funding) == len(ledger) == 1
    assert funding[0].channel == "copy_vault_funding"
    assert funding[0].instrument == vault and funding[0].exchange_ts_ms == 2_000
    assert ledger[0].channel == "copy_vault_ledger"
    assert ledger[0].exchange_ts_ms == 2_001
    assert funding[0].parsed_summary["proof_of_pnl_allowed"] is False
    assert ledger[0].provenance["forward_evidence_allowed"] is False


def test_user_accounting_websocket_streams_are_ack_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = "0x" + "b" * 40
    messages = [
        {
            "channel": "userFundings",
            "data": {"user": vault, "isSnapshot": False, "fundings": []},
        },
        {
            "channel": "subscriptionResponse",
            "data": {
                "method": "subscribe",
                "subscription": {"type": "userFundings", "user": vault},
            },
        },
        {
            "channel": "subscriptionResponse",
            "data": {
                "method": "subscribe",
                "subscription": {
                    "type": "userNonFundingLedgerUpdates", "user": vault,
                },
            },
        },
        {
            "channel": "userFundings",
            "data": {
                "user": vault, "isSnapshot": False,
                "fundings": [{
                    "time": int(C.time.time() * 1_000), "coin": "BTC",
                    "usdc": "-0.1", "szi": "1", "fundingRate": "0.0001",
                }],
            },
        },
        {
            "channel": "userNonFundingLedgerUpdates",
            "data": {
                "user": vault, "isSnapshot": False,
                "nonFundingLedgerUpdates": [{
                    "time": int(C.time.time() * 1_000), "hash": "0xledger",
                    "delta": {"type": "deposit", "usdc": 1.0},
                }],
            },
        },
    ]

    class FakeSocket:
        def __init__(self) -> None:
            self.release = asyncio.Event()

        async def send(self, _payload: str) -> None:
            return None

        def __aiter__(self):
            async def iterate():
                for message in messages:
                    yield json.dumps(message)
                await self.release.wait()
            return iterate()

    class FakeConnection:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    socket = FakeSocket()
    monkeypatch.setattr(
        C.websockets, "connect", lambda *_args, **_kwargs: FakeConnection(socket)
    )

    class Sink:
        def __init__(self) -> None:
            self.envelopes: list[C.TickEnvelope] = []

        async def emit_async(self, envelope: C.TickEnvelope) -> None:
            self.envelopes.append(envelope)

    async def scenario() -> None:
        sink = Sink()
        diagnostics: dict[str, int] = {}
        task = asyncio.create_task(C._socket_group(
            [vault], sink, observation_start_ms={}, live_ids={vault: set()},
            live_fill_counts={vault: 0}, unclassified_fill_counts={vault: 0},
            reconnect_counts={vault: 0},
            l2_request_queue=asyncio.Queue(), l2_known_coins=set(),
            subscription_attempts={}, subscription_attempts_dropped={},
            subscription_diagnostics=diagnostics,
        ))
        try:
            for _ in range(300):
                if diagnostics.get("user_funding_rows") and diagnostics.get(
                    "user_non_funding_ledger_rows"
                ):
                    break
                await asyncio.sleep(0.01)
            assert diagnostics["userFundings_messages_before_ack_dropped"] == 1
            assert diagnostics["userFundings_acknowledged"] == 1
            assert diagnostics["userNonFundingLedgerUpdates_acknowledged"] == 1
            assert diagnostics["user_funding_rows"] == 1
            assert diagnostics["user_non_funding_ledger_rows"] == 1
            assert {row.channel for row in sink.envelopes} == {
                "copy_vault_funding", "copy_vault_ledger",
            }
        finally:
            socket.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_l2_envelope_rejects_invalid_levels_and_timestamp() -> None:
    base = {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": 1_700_000_000_000,
            "levels": [[], []],
        },
    }
    kwargs = {
        "receive_wall_ms": 1_700_000_000_001,
        "receive_mono_ns": 22,
        "connection_id": "l2-test-1",
    }
    invalid_levels = json.loads(json.dumps(base))
    invalid_levels["data"]["levels"] = [[{"px": "NaN", "sz": "1", "n": 1}], []]
    invalid_timestamp = json.loads(json.dumps(base))
    invalid_timestamp["data"]["time"] = True

    assert C.l2_envelope(invalid_levels, **kwargs) is None
    assert C.l2_envelope(invalid_timestamp, **kwargs) is None


def test_l2_diagnostics_expose_unknown_coverage_without_claiming_full_capture() -> None:
    state = C.new_l2_state()
    state["received"] = 1
    C._record_l2_rejection(
        state,
        "invalid_levels",
        coin="BTC",
        at_ms=1_000,
        connection_id="conn-1",
    )

    diagnostics = C._l2_diagnostics(
        state,
        end_ms=2_500,
        requested_coins={"BTC", "ETH"},
    )

    assert diagnostics["received_frames"] == 1
    assert diagnostics["rejected_frames"] == 1
    assert diagnostics["rejected_by_reason"] == {"invalid_levels": 1}
    assert diagnostics["requested_markets"] == ["BTC", "ETH"]
    assert diagnostics["coverage_claim"] == "NOT_PROVEN"
    assert diagnostics["required_market_proof_window_status"] == "UNAVAILABLE"
    assert diagnostics["markets"]["BTC"]["coverage_status"] == "GAP_OPEN"
    assert diagnostics["markets"]["BTC"]["proof_window_status"] == "UNAVAILABLE"
    assert diagnostics["markets"]["BTC"]["last_receive_age_ms"] is None
    assert diagnostics["markets"]["BTC"]["received"] == 1
    assert diagnostics["markets"]["BTC"]["rejected"] == 1
    assert diagnostics["markets"]["BTC"]["rejected_by_reason"] == {
        "invalid_levels": 1
    }
    assert diagnostics["markets"]["ETH"]["coverage_status"] == "NO_MARKET_STATE"
    assert diagnostics["markets"]["ETH"]["proof_window_status"] == "UNAVAILABLE"
    assert diagnostics["markets"]["ETH"]["accepted"] is None
    assert diagnostics["markets"]["ETH"]["rejected_by_reason"] is None
    assert diagnostics["markets"]["ETH"]["coverage_status"] == "NO_MARKET_STATE"
    json.dumps(diagnostics)

    clean_state = C.new_l2_state()
    clean_envelope = C.l2_envelope(
        {
            "channel": "l2Book",
            "data": {
                "coin": "BTC",
                "time": 1_700_000_000_000,
                "levels": [
                    [{"px": "100", "sz": "2", "n": 1}],
                    [{"px": "101", "sz": "3", "n": 1}],
                ],
            },
        },
        receive_wall_ms=1_001,
        receive_mono_ns=1,
        connection_id="clean-connection",
    )
    assert clean_envelope is not None
    C._record_l2_accepted(clean_state, clean_envelope, receive_wall_ms=1_001)
    clean_diagnostics = C._l2_diagnostics(
        clean_state, end_ms=2_000, requested_coins={"BTC"}
    )
    assert clean_diagnostics["markets"]["BTC"]["proof_window_status"] == "UNPROVEN"
    assert clean_diagnostics["required_market_proof_window_status"] == "UNPROVEN"


def test_every_l2_rejection_reason_has_global_and_attributable_market_counts() -> None:
    malformed_levels = {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": 1_700_000_000_000,
            "levels": [[{"px": "NaN", "sz": "1", "n": 1}], []],
        },
    }
    malformed_timestamp = {
        "channel": "l2Book",
        "data": {"coin": "BTC", "time": "bad", "levels": [[], []]},
    }
    cases = [
        ("{bad-json", "invalid_json"),
        (json.dumps({"channel": "unexpected", "data": {"coin": "BTC"}}), "wrong_channel"),
        (json.dumps({"channel": "l2Book", "data": {"time": 1, "levels": [[], []]}}), "missing_coin"),
        (json.dumps(malformed_levels), "invalid_levels"),
        (json.dumps(malformed_timestamp), "invalid_timestamp"),
        (json.dumps(["not", "an", "object"]), "other_schema"),
    ]
    state = C.new_l2_state()
    for raw, expected_reason in cases:
        state["received"] += 1
        message, reason, coin = C.classify_l2_payload(raw)
        assert reason == expected_reason
        attributed_coin = coin or (
            C._l2_payload_coin(message) if message is not None else None
        )
        C._record_l2_rejection(
            state,
            reason,
            coin=attributed_coin,
            at_ms=2_000,
            connection_id="conn-rejects",
            affected_coins={"BTC"} if attributed_coin is None else None,
        )

    diagnostics = C._l2_diagnostics(
        state, end_ms=3_000, requested_coins={"BTC"}
    )
    assert diagnostics["rejected_by_reason"] == {
        "invalid_json": 1,
        "wrong_channel": 1,
        "missing_coin": 1,
        "invalid_levels": 1,
        "invalid_timestamp": 1,
        "other_schema": 1,
    }
    market = diagnostics["markets"]["BTC"]
    assert market["received"] == market["rejected"] == 3
    assert market["rejected_by_reason"] == {
        "wrong_channel": 1,
        "invalid_levels": 1,
        "invalid_timestamp": 1,
    }
    assert market["last_receive_age_ms"] is None
    assert market["coverage_status"] == "GAP_OPEN"
    assert market["proof_window_status"] == "UNAVAILABLE"
    assert diagnostics["required_market_proof_window_status"] == "UNAVAILABLE"
    assert len(diagnostics["unknown_market_rejections"]) == 3
    assert diagnostics["coverage_claim"] == "NOT_PROVEN"


def test_l2_per_market_counters_separate_rejections_duplicates_and_accepts() -> None:
    state = C.new_l2_state()
    C._record_l2_rejection(
        state,
        "invalid_levels",
        coin="BTC",
        at_ms=1_000,
        connection_id="conn-1",
    )
    envelope = C.l2_envelope(
        {
            "channel": "l2Book",
            "data": {
                "coin": "BTC",
                "time": 1_700_000_000_000,
                "levels": [
                    [{"px": "100", "sz": "2", "n": 1}],
                    [{"px": "101", "sz": "3", "n": 1}],
                ],
            },
        },
        receive_wall_ms=1_100,
        receive_mono_ns=10,
        connection_id="conn-1",
    )
    assert envelope is not None
    C._record_l2_accepted(state, envelope, receive_wall_ms=1_100)
    C._record_l2_duplicate(state, envelope)

    market = C._l2_diagnostics(
        state, end_ms=2_000, requested_coins={"BTC"}
    )["markets"]["BTC"]

    assert market["received"] == 3
    assert market["accepted"] == 1
    assert market["rejected"] == 1
    assert market["duplicates"] == 1
    assert market["rejected_by_reason"] == {"invalid_levels": 1}
    assert market["ignored_by_reason"] == {"duplicate_snapshot": 1}


def test_l2_history_is_bounded_and_counts_discarded_diagnostics() -> None:
    state = C.new_l2_state()
    for index in range(300):
        C._record_l2_disconnect(
            state,
            connection_id=f"conn-{index}",
            markets={"BTC"},
            at_ms=1_000 + index * 2,
            error_class="ConnectionClosed",
        )
        envelope = C.l2_envelope(
            {
                "channel": "l2Book",
                "data": {
                    "coin": "BTC",
                    "time": 1_700_000_000_000 + index,
                    "levels": [
                        [{"px": "100", "sz": "2", "n": 1}],
                        [{"px": "101", "sz": "3", "n": 1}],
                    ],
                },
            },
            receive_wall_ms=1_001 + index * 2,
            receive_mono_ns=index + 1,
            connection_id=f"conn-{index}-recovered",
        )
        assert envelope is not None
        C._record_l2_accepted(state, envelope, receive_wall_ms=1_001 + index * 2)

    assert len(state["connection_events"]) == C.MAX_L2_DIAGNOSTIC_RECORDS
    assert state["connection_events_dropped"] == 300 - C.MAX_L2_DIAGNOSTIC_RECORDS
    market = state["markets"]["BTC"]
    assert len(market["gaps"]) == C.MAX_L2_DIAGNOSTIC_RECORDS
    assert market["gaps_dropped"] == 300 - C.MAX_L2_DIAGNOSTIC_RECORDS


def test_l2_collector_rejects_unknown_channels_and_recovers_after_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": 1_700_000_000_000,
            "levels": [
                [{"px": "100", "sz": "2", "n": 1}],
                [{"px": "101", "sz": "3", "n": 2}],
            ],
        },
    }

    class FakeSocket:
        def __init__(
            self, messages: list[dict[str, object]], *, fail_after: bool = False
        ) -> None:
            self.messages = messages
            self.fail_after = fail_after
            self.release = asyncio.Event()

        async def send(self, payload: str) -> None:
            assert json.loads(payload)["method"] in {"subscribe", "ping"}

        def __aiter__(self):
            async def iterate():
                for message in self.messages:
                    yield json.dumps(message)
                if self.fail_after:
                    raise ConnectionError("simulated disconnect")
                await self.release.wait()

            return iterate()

    class FakeConnection:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    first = FakeSocket(
        [
            {"channel": "pong"},
            {"channel": "unexpected", "data": {"coin": "BTC"}},
            valid,
            {
                "channel": "subscriptionResponse",
                "data": {
                    "method": "subscribe",
                    "subscription": {"type": "l2Book", "coin": "BTC"},
                },
            },
            valid,
            valid,
        ],
        fail_after=True,
    )
    resumed = {**valid, "data": {**valid["data"], "time": 1_700_000_000_001}}
    second = FakeSocket(
        [
            {
                "channel": "subscriptionResponse",
                "data": {
                    "method": "subscribe",
                    "subscription": {"type": "l2Book", "coin": "BTC"},
                },
            },
            resumed,
        ]
    )
    connections = iter([first, second])
    monkeypatch.setattr(
        C.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnection(next(connections)),
    )

    class Sink:
        def __init__(self) -> None:
            self.envelopes: list[C.TickEnvelope] = []

        async def emit_async(self, envelope: C.TickEnvelope) -> None:
            self.envelopes.append(envelope)

    async def scenario() -> None:
        state = C.new_l2_state()
        sink = Sink()
        task = asyncio.create_task(
            C._dynamic_l2_collector(
                sink,
                asyncio.Queue(),
                {"BTC"},
                state,
            )
        )
        try:
            for _ in range(500):
                if state.get("frames", 0) >= 2:
                    break
                await asyncio.sleep(0.01)
            assert state.get("frames") == 2
            assert state.get("reconnects") == 1
            assert state.get("rejected_by_reason", {}).get("wrong_channel") == 1
            assert state.get("rejected_by_reason", {}).get("subscription_not_active") == 1
            assert state.get("heartbeats_received") == 1
            assert state.get("duplicates") == 1
            assert len(sink.envelopes) == 2

            diagnostics = C._l2_diagnostics(
                state,
                end_ms=1_700_000_010_000,
                requested_coins={"BTC"},
            )
            market = diagnostics["markets"]["BTC"]
            assert market["received"] == 5
            assert market["accepted"] == 2
            assert market["rejected"] == 2
            assert market["duplicates"] == 1
            assert market["rejected_by_reason"] == {
                "wrong_channel": 1,
                "subscription_not_active": 1,
            }
            assert market["ignored_by_reason"] == {"duplicate_snapshot": 1}
            assert market["candidate_l2_frames"] == 4
            assert len(market["gaps"]) == 2
            assert all(gap["recovery_at_ms"] is not None for gap in market["gaps"])
            assert all(not gap["continuity_proven"] for gap in market["gaps"])
            assert market["coverage_status"] == "SNAPSHOTS_CONTINUITY_UNPROVEN"
            assert market["proof_window_status"] == "UNAVAILABLE"
            assert diagnostics["required_market_proof_window_status"] == "UNAVAILABLE"
            json.dumps(diagnostics)
        finally:
            second.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_snapshot_and_live_userfills_are_separate_families() -> None:
    snapshot, snapshot_fills = C.userfills_envelope(
        {
            "channel": "userFills",
            "data": {
                "user": "0x" + "1" * 40,
                "isSnapshot": True,
                "fills": [
                    {
                        "coin": "BTC",
                        "px": "100",
                        "sz": "1",
                        "side": "B",
                        "time": 1_000,
                        "dir": "Open Long",
                        "hash": "0xsnap",
                        "tid": 1,
                        "oid": 1,
                    }
                ],
            },
        },
        vault="0x" + "1" * 40,
        receive_wall_ms=1_010,
        receive_mono_ns=123,
        connection_id="copy-test",
    )
    assert snapshot is not None
    assert snapshot.channel == "copy_vault_snapshot"
    assert snapshot.event_kind.value == "SNAPSHOT"
    assert snapshot.parsed_summary["is_snapshot"] is True
    assert snapshot_fills[0]["received_at_ms"] == 1_010
    assert snapshot_fills[0]["recv_mono_ns"] == 123

    live, live_fills = C.userfills_envelope(
        {
            "channel": "userFills",
            "data": {
                "user": "0x" + "1" * 40,
                "isSnapshot": False,
                "fills": [
                    {
                        "coin": "BTC",
                        "px": "101",
                        "sz": "1",
                        "side": "A",
                        "time": 1_020,
                        "dir": "Close Long",
                        "hash": "0xlive",
                        "tid": 2,
                        "oid": 2,
                    }
                ],
            },
        },
        vault="0x" + "1" * 40,
        receive_wall_ms=1_025,
        receive_mono_ns=456,
        connection_id="copy-test",
    )
    assert live is not None
    assert live.channel == "copy_vault_fills"
    assert live.event_kind.value == "EVENT"
    assert live.exchange_ts_ms == 1_020
    assert live_fills[0]["connection_id"] == "copy-test"


def test_empty_userfills_snapshot_is_preserved_as_a_snapshot_event() -> None:
    envelope, fills = C.userfills_envelope(
        {
            "channel": "userFills",
            "data": {"user": "0x" + "1" * 40, "isSnapshot": True, "fills": []},
        },
        vault="0x" + "1" * 40,
        receive_wall_ms=1_010,
        receive_mono_ns=123,
        connection_id="copy-test",
    )

    assert envelope is not None
    assert envelope.channel == "copy_vault_snapshot"
    assert envelope.parsed_summary["is_snapshot"] is True
    assert envelope.parsed_summary["event_count"] == 0
    assert fills == []


def test_missing_snapshot_flag_is_preserved_but_never_classified_live() -> None:
    envelope, fills = C.userfills_envelope(
        {
            "channel": "userFills",
            "data": {
                "user": "0x" + "1" * 40,
                "fills": [{
                    "coin": "BTC", "px": "100", "sz": "1", "side": "B",
                    "time": 1_000, "dir": "Open Long", "hash": "0xunknown",
                    "tid": 3, "oid": 3,
                }],
            },
        },
        vault="0x" + "1" * 40,
        receive_wall_ms=1_010,
        receive_mono_ns=123,
        connection_id="copy-test",
    )
    assert envelope is not None
    assert envelope.channel == "copy_vault_fills"
    assert envelope.event_kind == "UNCLASSIFIED"
    assert envelope.parsed_summary["snapshot_flag_status"] == "MISSING_OR_INVALID"
    assert envelope.parsed_summary["is_snapshot"] is None
    assert fills[0]["isSnapshot"] is None


def test_selection_envelope_is_observation_only_and_causal() -> None:
    address = "0x" + "2" * 40
    selection = {
        "selected_at_ms": 5_000,
        "source": "https://stats-data.hyperliquid.xyz/Mainnet/vaults",
        "filters": {"min_tvl_usd": 100000, "min_age_days": 45},
    }
    envelope = C.selection_envelope(
        {
            "address": address,
            "tvl_usd": 1_000_000,
            "age_j": 100,
            "apr_pct": 10,
        },
        selection,
    )
    record = envelope.as_record(written_ts_ms=5_010)
    assert record["instrument"] == address
    assert record["exchange_ts_ms"] is None
    assert record["provenance"]["selection_causal"] is True
    assert record["parsed_summary"]["observation_only"] is True


def test_exact_window_backfill_splits_at_2000_response_cap() -> None:
    address = "0x" + "3" * 40

    async def scenario() -> None:
        queried_windows: list[tuple[int, int]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            start = int(body["startTime"])
            end = int(body["endTime"])
            queried_windows.append((start, end))
            if end - start > 5_000:
                rows = [
                    {
                        "coin": "BTC",
                        "px": "100",
                        "sz": "1",
                        "side": "B",
                        "time": start + index,
                        "dir": "Open Long",
                        "hash": f"0x{index:064x}",
                        "tid": index,
                        "oid": index,
                    }
                    for index in range(C.CAP_USERFILLS)
                ]
            else:
                rows = [
                    {
                        "coin": "BTC",
                        "px": "100",
                        "sz": "1",
                        "side": "B",
                        "time": start + 1,
                        "dir": "Open Long",
                        "hash": f"0x{start:064x}",
                        "tid": start,
                        "oid": start,
                    }
                ]
            return httpx.Response(200, json=rows)

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.exact_window_backfill(
            client,
            address,
            start_ms=10_000,
            end_ms=20_000,
        )
        await client.aclose()
        assert audit["status"] == "COMPLETE"
        assert audit["requests"] == 3
        assert audit["splits"] == 1
        assert len(rows) == 2
        assert queried_windows == [
            (10_000, 20_000),
            (10_000, 15_000),
            (15_001, 20_000),
        ]

    asyncio.run(scenario())


def test_exact_window_backfill_keeps_original_fill_for_safe_history_storage() -> None:
    address = "0x" + "7" * 40
    source_fill = {
        "coin": "BTC", "px": "100", "sz": "1", "side": "B",
        "time": 10_001, "dir": "Open Long", "fee": "0.12",
        "feeToken": "USDC", "closedPnl": "0", "hash": "0xoriginal",
    }

    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[source_fill])

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.exact_window_backfill(
            client, address, start_ms=10_000, end_ms=20_000,
        )
        await client.aclose()

        assert audit["status"] == "COMPLETE"
        assert rows[0]["raw_fill"] == source_fill

    asyncio.run(scenario())


def test_rest_backfill_envelope_is_historical_and_not_forward_evidence() -> None:
    address = "0x" + "8" * 40
    raw_fill = {
        "coin": "ETH", "px": "2000", "sz": "0.5", "side": "A",
        "time": 9_000, "dir": "Close Long", "fee": "0.04",
        "feeToken": "USDC", "hash": "0xhistorical",
    }
    audit = {
        "status": "COMPLETE", "requested_start_ms": 1_000,
        "requested_end_ms": 8_999, "requests": 1, "rows": 1,
    }

    envelopes = C.rest_backfill_envelopes(
        [{"raw_fill": raw_fill}], vault=address, audit=audit,
        receive_wall_ms=10_000, receive_mono_ns=123,
    )

    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope.channel == "copy_vault_snapshot"
    assert envelope.source_id == "hyperliquid_public_userfills_backfill"
    assert envelope.provenance["transport"] == "https"
    assert envelope.provenance["forward_evidence_allowed"] is False
    assert envelope.raw_payload["data"]["isSnapshot"] is True
    assert envelope.raw_payload["data"]["fills"] == [raw_fill]
    assert envelope.raw_payload["backfill_audit"] == audit


def test_rest_weight_pacer_leaves_headroom_under_ip_limit() -> None:
    import asyncio

    now = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    async def scenario() -> None:
        pacer = C.RestWeightPacer(
            budget_weight_per_minute=600,
            monotonic_fn=lambda: now[0],
            sleep_fn=fake_sleep,
        )
        await pacer.before_request()
        now[0] += 0.1
        await pacer.before_request()

    asyncio.run(scenario())
    assert sleeps == [pytest.approx(11.9)]


def test_historical_backfill_resumes_durable_cursor_and_keeps_known_gaps(monkeypatch) -> None:
    assert C.DEFAULT_HISTORY_LOOKBACK_HOURS == 72.0
    vault = "0x" + "2" * 40
    selection_ms = 2_000_000_000_000
    checkpoint_ms = selection_ms - 60 * 60 * 1000
    observed: dict[str, int] = {}

    async def fake_backfill(client, address, *, start_ms, end_ms, **kwargs):
        observed["start_ms"] = start_ms
        observed["end_ms"] = end_ms
        return [], {
            "status": "COMPLETE",
            "requested_start_ms": start_ms,
            "requested_end_ms": end_ms,
            "rows": 0,
            "requests": 1,
            "pending_windows": 0,
            "request_budget_exhausted": False,
            "invalid_fill_count": 0,
            "failed_windows": [],
            "cap_blocked_windows": [],
            "retention_cap_reached": False,
        }

    monkeypatch.setattr(C, "exact_window_backfill", fake_backfill)

    async def fake_accounting_backfill(client, address, **kwargs):
        return [], {"status": "COMPLETE", "event_count": 0}

    monkeypatch.setattr(
        C, "exact_window_accounting_backfill", fake_accounting_backfill
    )
    known_gap = {"start_ms": checkpoint_ms - 100, "end_ms": checkpoint_ms - 1, "reason": "KNOWN"}
    reports, envelopes = asyncio.run(
        C.collect_historical_backfills(
            [vault],
            selection_ts_ms=selection_ms,
            lookback_hours=6,
            history_checkpoints={vault: {
                "last_complete_end_ms": checkpoint_ms,
                "unresolved_gaps": [known_gap],
            }},
        )
    )

    report = reports[vault]
    assert observed["start_ms"] == checkpoint_ms
    assert observed["end_ms"] == selection_ms - 1
    assert report["status"] == "PARTIAL"
    assert report["request_audit_status"] == "COMPLETE"
    assert report["checkpoint_advance_allowed"] is True
    assert report["unresolved_gaps"] == [known_gap]
    assert report["forward_evidence_allowed"] is False
    assert envelopes == []


def test_historical_backfill_advances_past_public_retention_cap_with_gap(monkeypatch) -> None:
    vault = "0x" + "3" * 40
    selection_ms = 2_000_000_000_000
    old_checkpoint_ms = selection_ms - 100 * 60 * 60 * 1000
    observed: dict[str, int] = {}

    async def fake_backfill(client, address, *, start_ms, end_ms, **kwargs):
        observed["start_ms"] = start_ms
        return [], {
            "status": "PARTIAL",
            "requested_start_ms": start_ms,
            "requested_end_ms": end_ms,
            "rows": 10_000,
            "requests": 12,
            "pending_windows": 0,
            "request_budget_exhausted": False,
            "invalid_fill_count": 0,
            "failed_windows": [],
            "cap_blocked_windows": [],
            "retention_cap_reached": True,
            "oldest_fill_ts_ms": start_ms + 3_600_000,
        }

    monkeypatch.setattr(C, "exact_window_backfill", fake_backfill)

    async def fake_accounting_backfill(client, address, **kwargs):
        return [], {"status": "COMPLETE", "event_count": 0}

    monkeypatch.setattr(
        C, "exact_window_accounting_backfill", fake_accounting_backfill
    )
    reports, _envelopes = asyncio.run(
        C.collect_historical_backfills(
            [vault],
            selection_ts_ms=selection_ms,
            lookback_hours=72,
            history_checkpoints={vault: {
                "last_reconciled_end_ms": old_checkpoint_ms,
                "unresolved_gaps": [],
            }},
        )
    )

    report = reports[vault]
    assert observed["start_ms"] == selection_ms - 1 - 72 * 60 * 60 * 1000
    assert report["status"] == "PARTIAL"
    assert report["request_audit_status"] == "PARTIAL"
    assert report["checkpoint_advance_allowed"] is True
    assert report["unresolved_gaps"] == [
        {
            "start_ms": old_checkpoint_ms,
            "end_ms": observed["start_ms"] - 1,
            "reason": "HISTORY_LOOKBACK_LIMIT_72H",
        },
        {
            "start_ms": observed["start_ms"],
            "end_ms": observed["start_ms"] + 3_600_000 - 1,
            "reason": "PUBLIC_10000_FILL_RETENTION_LIMIT",
        },
    ]


def test_exact_window_backfill_fails_closed_when_request_budget_is_exhausted() -> None:
    address = "0x" + "6" * 40

    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            start = int(body["startTime"])
            rows = [
                {
                    "coin": "BTC",
                    "px": "100",
                    "sz": "1",
                    "side": "B",
                    "time": start + index,
                    "dir": "Open Long",
                    "hash": f"0x{index:064x}",
                    "tid": index,
                    "oid": index,
                }
                for index in range(C.CAP_USERFILLS)
            ]
            return httpx.Response(200, json=rows)

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )
        rows, audit = await C.exact_window_backfill(
            client,
            address,
            start_ms=10_000,
            end_ms=30_000,
            max_requests=2,
        )
        await client.aclose()
        assert rows == []
        assert audit["status"] == "PARTIAL"
        assert audit["requests"] == 2
        assert audit["request_budget_exhausted"] is True
        assert audit["pending_windows"] > 0

    asyncio.run(scenario())


def test_bundle_keeps_forward_selection_metadata(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "bundle"
    writer = C.PartitionedTickDatasetWriter(raw, rotate_bytes=10_000_000, flush_every=1)
    address = "0x" + "4" * 40
    envelope, fills = C.userfills_envelope(
        {
            "channel": "userFills",
            "data": {
                "user": address,
                "isSnapshot": False,
                "fills": [
                    {
                        "coin": "ETH",
                        "px": "2000",
                        "sz": "1",
                        "side": "B",
                        "time": 10_000,
                        "dir": "Open Long",
                        "hash": "0xfill",
                        "tid": 1,
                        "oid": 1,
                    }
                ],
            },
        },
        vault=address,
        receive_wall_ms=10_010,
        receive_mono_ns=123,
        connection_id="copy-vault-test",
    )
    assert envelope is not None
    writer.append(envelope)
    writer.rotate_all()

    fill_id = C.canonical_fill_id(fills[0])
    index = C.build_copy_vault_bundle(
        raw,
        output,
        collector_version="a" * 40,
        reconciliation={
            address: {
                "status": "MATCHED",
                "live_count": 1,
                "reference_count": 1,
                "matched_count": 1,
                "missing_from_live": 0,
                "live_only": 0,
            }
        },
        queue_drops={},
        selection={
            "selected_at_ms": 9_000,
            "observation_only": True,
            "vaults": [{"address": address}],
        },
        collection_run_id="copy-vault-test-run",
    )
    assert fill_id
    assert index["collection_kind"] == "copy_vault_forward"
    assert index["collection_run_id"] == "copy-vault-test-run"
    manifest_paths = list((output / "manifests").glob("*.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["family"] == "copy_vault_fills"
    assert manifest["collection_run_id"] == "copy-vault-test-run"
    assert manifest["reconciliation"]["status"] == "MATCHED"
    assert manifest["copy_vault_selection"]["forward_only"] is True


def test_market_context_bundle_is_safe_but_never_pnl_proof(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "bundle"
    writer = C.PartitionedTickDatasetWriter(
        raw, rotate_bytes=10_000_000, flush_every=1
    )
    received = int(C.time.time() * 1_000)
    common = {
        "url": C.WS_URL,
        "network": "mainnet",
        "venue": "hyperliquid",
        "access": "read_only",
        "transport": "websocket",
        "authenticated": False,
        "copy_vault_same_run_market_evidence": True,
    }
    envelopes = C.copy_vault_market_envelopes(
        {
            "channel": "bbo",
            "data": {
                "coin": "kPEPE", "time": received - 1,
                "bbo": [{"px": "0.01", "sz": "10"}, {"px": "0.011", "sz": "20"}],
            },
        },
        receive_wall_ms=received,
        receive_mono_ns=100,
        connection_id="market-bundle-test",
    )
    envelopes += C.copy_vault_market_envelopes(
        {
            "channel": "trades",
            "data": [{
                "coin": "kPEPE", "time": received - 1, "px": "0.0105",
                "sz": "2", "side": "B", "hash": "0xtrade", "tid": 10,
            }],
        },
        receive_wall_ms=received,
        receive_mono_ns=101,
        connection_id="market-bundle-test",
    )
    envelopes += C.copy_vault_market_envelopes(
        {"channel": "activeAssetCtx", "data": {"coin": "kPEPE", "ctx": {"markPx": "0.0105"}}},
        receive_wall_ms=received,
        receive_mono_ns=102,
        connection_id="market-bundle-test",
    )
    vault = "0x" + "c" * 40
    funding_rows, funding_error = C.copy_vault_accounting_envelopes(
        {
            "channel": "userFundings",
            "data": {
                "user": vault, "isSnapshot": False,
                "fundings": [{
                    "time": received - 1, "coin": "kPEPE", "usdc": "-0.1",
                    "szi": "1", "fundingRate": "0.0001",
                }],
            },
        },
        vault=vault,
        receive_wall_ms=received,
        receive_mono_ns=103,
        connection_id="market-bundle-test",
    )
    ledger_rows, ledger_error = C.copy_vault_accounting_envelopes(
        {
            "channel": "userNonFundingLedgerUpdates",
            "data": {
                "user": vault, "isSnapshot": False,
                "nonFundingLedgerUpdates": [{
                    "time": received - 1, "hash": "0xledger",
                    "delta": {"type": "deposit", "usdc": 1.0},
                }],
            },
        },
        vault=vault,
        receive_wall_ms=received,
        receive_mono_ns=104,
        connection_id="market-bundle-test",
    )
    assert funding_error is None and ledger_error is None
    envelopes.extend(funding_rows)
    envelopes.extend(ledger_rows)
    for envelope in envelopes:
        envelope.provenance.update(common)
        writer.append(envelope)
    writer.rotate_all()

    index = C.build_copy_vault_bundle(
        raw,
        output,
        collector_version="a" * 40,
        reconciliation={},
        queue_drops={},
        selection={"selected_at_ms": received},
        collection_run_id="market-context-test",
    )

    assert index["shard_count"] == 5
    assert index["partial_count"] == 5  # remote release SHA is not verified here
    manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (output / "manifests").glob("*.json")
    ]
    assert {row["family"] for row in manifests} == {
        "copy_vault_bbo", "copy_vault_trades", "copy_vault_active_asset_ctx",
        "copy_vault_funding", "copy_vault_ledger",
    }
    assert all(row["quality_status"] == "PARTIAL" for row in manifests)
    assert all(row["replay_compatible"] is True for row in manifests)
    assert all(row["proof_of_pnl_allowed"] is False for row in manifests)


def test_bundle_labels_rest_backfill_historical_and_not_forward(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "bundle"
    writer = C.PartitionedTickDatasetWriter(raw, rotate_bytes=10_000_000, flush_every=1)
    address = "0x55"
    envelope = C.rest_backfill_envelopes(
        [{"raw_fill": {
            "coin": "BTC", "px": "100", "sz": "1", "side": "B",
            "time": 9_000, "dir": "Open Long", "hash": "0xhistorical",
        }}],
        vault=address,
        audit={"status": "COMPLETE", "requested_start_ms": 1_000, "requested_end_ms": 9_001},
        receive_wall_ms=10_000,
        receive_mono_ns=123,
    )[0]
    writer.append(envelope)
    writer.rotate_all()

    report = {
        address: {
            "status": "COMPLETE", "rows": 1,
            "window_kind": "PRE_SELECTION_HISTORICAL_RESEARCH_ONLY",
            "forward_evidence_allowed": False,
        }
    }
    index = C.build_copy_vault_bundle(
        raw,
        output,
        collector_version="a" * 40,
        reconciliation={},
        queue_drops={},
        selection={"selected_at_ms": 10_000},
        collection_run_id="copy-vault-history-test",
        historical_backfill=report,
    )

    [manifest_path] = (output / "manifests").glob("*.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert index["collection_kind"] == "copy_vault_forward_plus_historical_research"
    assert manifest["copy_vault_selection"]["forward_only"] is False
    assert manifest["copy_vault_selection"]["historical_only"] is True
    assert manifest["copy_vault_history"]["status"] == "COMPLETE"
    assert manifest["reconciliation"]["forward_evidence_allowed"] is False
    # Before GitHub release upload the asset is intentionally not SAFE yet.
    assert manifest["quality_status"] == "PARTIAL"
    assert "REMOTE_ASSET_NOT_VERIFIED" in manifest["quality_reasons"]



def test_copy_vault_lane_respects_hyperliquid_unique_user_limit() -> None:
    allowed = ["0x" + f"{index:040x}" for index in range(10)]
    assert C.validate_user_subscription_budget(allowed) == 10

    too_many = ["0x" + f"{index:040x}" for index in range(11)]
    import pytest
    with pytest.raises(ValueError, match="10 per IP"):
        C.validate_user_subscription_budget(too_many)


def test_copy_vault_lane_counts_unique_users_only() -> None:
    address = "0x" + "1" * 40
    assert C.validate_user_subscription_budget([address, address.upper()]) == 1



def test_reconcile_requires_per_vault_subscription_start() -> None:
    address = "0x" + "5" * 40

    async def scenario() -> None:
        result = await C.reconcile_forward_window(
            [address],
            start_ms_by_vault={},
            end_ms=20_000,
            live_ids={},
        )
        report = result[address]
        assert report["status"] == "UNAVAILABLE"
        assert report["audit"]["reason"] == "NO_LIVE_SUBSCRIPTION_START"
        assert report["audit"]["requested_start_ms"] is None

    asyncio.run(scenario())


def test_subscription_ack_parser_requires_matching_subscribe_response() -> None:
    expected = {"type": "userFills", "user": "0x" + "a" * 40}
    matching = {
        "channel": "subscriptionResponse",
        "data": {"method": "subscribe", "subscription": expected},
    }
    other_user = {
        "channel": "subscriptionResponse",
        "data": {
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": "0x" + "b" * 40},
        },
    }
    rejected = {
        "channel": "subscriptionResponse",
        "data": {
            "method": "subscribe",
            "subscription": expected,
            "error": "subscription rejected",
        },
    }

    assert C.classify_subscription_ack(matching) == (
        "ACKNOWLEDGED",
        ("userFills", "0x" + "a" * 40),
        None,
    )
    assert C.classify_subscription_ack(other_user)[1] == (
        "userFills",
        "0x" + "b" * 40,
    )
    assert C.classify_subscription_ack(rejected) == (
        "REJECTED",
        ("userFills", "0x" + "a" * 40),
        "subscription rejected",
    )
    assert C.classify_subscription_ack({"channel": "pong"}) is None
    assert C.classify_subscription_ack(
        {"channel": "subscriptionResponse", "data": {"method": "subscribe"}}
    )[0] == "INVALID"


def test_l2_collector_requires_matching_ack_before_accepting_book(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": 1_700_000_000_000,
            "levels": [
                [{"px": "100", "sz": "2", "n": 1}],
                [{"px": "101", "sz": "2", "n": 1}],
            ],
        },
    }

    class FakeSocket:
        def __init__(self) -> None:
            self.release = asyncio.Event()

        async def send(self, _payload: str) -> None:
            return None

        def __aiter__(self):
            async def iterate():
                yield json.dumps(valid)
                yield json.dumps({
                    "channel": "subscriptionResponse",
                    "data": {
                        "method": "subscribe",
                        "subscription": {"type": "l2Book", "coin": "ETH"},
                    },
                })
                yield json.dumps({
                    "channel": "subscriptionResponse",
                    "data": {
                        "method": "subscribe",
                        "subscription": {"type": "l2Book", "coin": "BTC"},
                    },
                })
                yield json.dumps(valid)
                await self.release.wait()

            return iterate()

    class FakeConnection:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    socket = FakeSocket()
    monkeypatch.setattr(
        C.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnection(socket),
    )

    class Sink:
        def __init__(self) -> None:
            self.envelopes: list[C.TickEnvelope] = []

        async def emit_async(self, envelope: C.TickEnvelope) -> None:
            self.envelopes.append(envelope)

    async def scenario() -> None:
        state = C.new_l2_state()
        sink = Sink()
        task = asyncio.create_task(
            C._dynamic_l2_collector(sink, asyncio.Queue(), {"BTC"}, state)
        )
        try:
            for _ in range(100):
                market = state.get("markets", {}).get("BTC", {})
                if market.get("accepted") == 1:
                    break
                await asyncio.sleep(0.01)
            market = state["markets"]["BTC"]
            assert market["accepted"] == 1
            assert market["rejected"] == 1
            assert market["subscription_status"] == "ACTIVE"
            assert state["subscription_ack_mismatches"] == 1
            assert len(sink.envelopes) == 1
        finally:
            socket.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_l2_rejected_subscription_never_accepts_book(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book = {
        "channel": "l2Book",
        "data": {
            "coin": "BTC",
            "time": 1_700_000_000_000,
            "levels": [
                [{"px": "100", "sz": "1", "n": 1}],
                [{"px": "101", "sz": "1", "n": 1}],
            ],
        },
    }
    rejected = {
        "channel": "subscriptionResponse",
        "data": {
            "method": "subscribe",
            "subscription": {"type": "l2Book", "coin": "BTC"},
            "error": "subscription rejected",
        },
    }

    class FakeSocket:
        def __init__(self) -> None:
            self.release = asyncio.Event()

        async def send(self, _payload: str) -> None:
            return None

        def __aiter__(self):
            async def iterate():
                yield json.dumps(rejected)
                yield json.dumps(book)
                await self.release.wait()

            return iterate()

    class FakeConnection:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    socket = FakeSocket()
    monkeypatch.setattr(
        C.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnection(socket),
    )

    class Sink:
        async def emit_async(self, _envelope: C.TickEnvelope) -> None:
            raise AssertionError("rejected L2 subscription must not emit a book")

    async def scenario() -> None:
        state = C.new_l2_state()
        task = asyncio.create_task(
            C._dynamic_l2_collector(Sink(), asyncio.Queue(), {"BTC"}, state)
        )
        try:
            for _ in range(100):
                if state.get("rejected_by_reason", {}).get("subscription_not_active"):
                    break
                await asyncio.sleep(0.01)
            market = state["markets"]["BTC"]
            assert market["subscription_status"] == "REJECTED"
            assert market["accepted"] == 0
            assert state["rejected_by_reason"]["subscription_rejected"] == 1
            assert state["rejected_by_reason"]["subscription_not_active"] == 1
        finally:
            socket.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_userfills_forward_starts_after_ack_and_reconnect_reanchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    address = "0x" + "c" * 40
    clock = [1_700_000_000.0]

    def fill(ts: int, tid: int) -> dict[str, object]:
        return {
            "coin": "BTC",
            "px": "100",
            "sz": "1",
            "side": "B",
            "time": ts,
            "dir": "Open Long",
            "hash": f"0x{tid:x}",
            "tid": tid,
            "oid": tid,
        }

    def event(*, snapshot: bool, ts: int, tid: int) -> dict[str, object]:
        return {
            "channel": "userFills",
            "data": {"user": address, "isSnapshot": snapshot, "fills": [fill(ts, tid)]},
        }

    ack = {
        "channel": "subscriptionResponse",
        "data": {"method": "subscribe", "subscription": {"type": "userFills", "user": address}},
    }

    class FakeSocket:
        def __init__(
            self,
            messages: list[dict[str, object]],
            *,
            disconnect: bool = False,
            advance_clock_on_ack: bool = False,
            delay_before_ack_s: float = 0.0,
        ) -> None:
            self.messages = messages
            self.disconnect = disconnect
            self.advance_clock_on_ack = advance_clock_on_ack
            self.delay_before_ack_s = delay_before_ack_s
            self.release = asyncio.Event()

        async def send(self, _payload: str) -> None:
            return None

        def __aiter__(self):
            async def iterate():
                for message in self.messages:
                    if message is ack and self.advance_clock_on_ack:
                        clock[0] = 1_700_000_010.0
                    if message is ack and self.delay_before_ack_s:
                        await asyncio.sleep(self.delay_before_ack_s)
                    yield json.dumps(message)
                if self.disconnect:
                    raise ConnectionError("simulated reconnect")
                await self.release.wait()

            return iterate()

    first = FakeSocket([ack], disconnect=True)
    second = FakeSocket(
        [
            event(snapshot=False, ts=1_700_000_005_000, tid=1),
            ack,
            event(snapshot=True, ts=1_699_999_000_000, tid=2),
            event(snapshot=True, ts=1_700_000_010_200, tid=5),
            event(snapshot=True, ts=1_700_000_010_200, tid=5),
            event(snapshot=False, ts=1_700_000_010_200, tid=5),
            event(snapshot=False, ts=1_700_000_010_000, tid=4),
            event(snapshot=False, ts=1_700_000_010_500, tid=3),
            event(snapshot=False, ts=1_700_000_010_500, tid=3),
        ],
        advance_clock_on_ack=True,
        delay_before_ack_s=0.08,
    )
    connections = iter([first, second])
    monkeypatch.setattr(
        C.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnection(next(connections)),
    )
    monkeypatch.setattr(C.time, "time", lambda: clock[0])
    monkeypatch.setattr(C, "SUBSCRIPTION_ACK_TIMEOUT_S", 0.05)

    class FakeConnection:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Sink:
        def __init__(self) -> None:
            self.envelopes: list[C.TickEnvelope] = []

        async def emit_async(self, envelope: C.TickEnvelope) -> None:
            self.envelopes.append(envelope)

    async def scenario() -> None:
        starts: dict[str, int] = {}
        subscription_attempts: dict[str, list[dict[str, object]]] = {}
        subscription_attempts_dropped: dict[str, int] = {}
        subscription_diagnostics: dict[str, int] = {}
        live_ids: dict[str, set[str]] = {address: set()}
        live_fill_counts: dict[str, int] = {address: 0}
        unclassified_fill_counts: dict[str, int] = {address: 0}
        reconnect_counts: dict[str, int] = {address: 0}
        snapshot_fill_ids: dict[str, set[str]] = {address: set()}
        sink = Sink()
        task = asyncio.create_task(
            C._socket_group(
                [address],
                sink,
                observation_start_ms=starts,
                live_ids=live_ids,
                live_fill_counts=live_fill_counts,
                unclassified_fill_counts=unclassified_fill_counts,
                reconnect_counts=reconnect_counts,
                l2_request_queue=asyncio.Queue(),
                l2_known_coins=set(),
                subscription_attempts=subscription_attempts,
                subscription_attempts_dropped=subscription_attempts_dropped,
                subscription_diagnostics=subscription_diagnostics,
                snapshot_fill_ids=snapshot_fill_ids,
            )
        )
        try:
            for _ in range(500):
                attempts = subscription_attempts.get(address, [])
                if len(attempts) >= 2 and len(sink.envelopes) >= 7:
                    break
                await asyncio.sleep(0.01)
            attempts = subscription_attempts[address]
            assert len(attempts) == 2
            assert attempts[0]["status"] == "INVALIDATED"
            assert attempts[1]["status"] == "ACTIVE"
            assert attempts[1]["late_ack"] is True
            assert attempts[1]["timed_out_at_ms"] is not None
            assert starts[address] == 1_700_000_010_000
            assert live_fill_counts[address] == 1
            _, normalized_fills = C.userfills_envelope(
                event(snapshot=False, ts=1_700_000_010_500, tid=3),
                vault=address,
                receive_wall_ms=1_700_000_010_501,
                receive_mono_ns=1,
                connection_id="expected",
            )
            assert len(normalized_fills) == 1
            assert live_ids[address] == {
                C.canonical_fill_id(normalized_fills[0])
            }
            assert subscription_diagnostics["messages_before_ack_dropped"] == 1
            assert subscription_diagnostics["acknowledged"] == 2
            assert subscription_diagnostics["duplicate_snapshot_fill_observed"] == 1
            assert subscription_diagnostics["snapshot_stream_overlap_dropped"] == 1
            assert subscription_diagnostics["ambiguous_ack_boundary_fill_dropped"] == 1
            assert subscription_diagnostics["duplicate_stream_fill_dropped"] == 1
        finally:
            second.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_userfills_rejected_subscription_never_starts_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    address = "0x" + "d" * 40
    rejected = {
        "channel": "subscriptionResponse",
        "data": {
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": address},
            "error": "subscription rejected",
        },
    }
    fill_event = {
        "channel": "userFills",
        "data": {
            "user": address,
            "isSnapshot": False,
            "fills": [
                {
                    "coin": "BTC",
                    "px": "100",
                    "sz": "1",
                    "side": "B",
                    "time": 1_700_000_010_000,
                    "dir": "Open Long",
                    "hash": "0xrejected",
                    "tid": 4,
                    "oid": 4,
                }
            ],
        },
    }

    class FakeSocket:
        def __init__(self) -> None:
            self.release = asyncio.Event()

        async def send(self, _payload: str) -> None:
            return None

        def __aiter__(self):
            async def iterate():
                yield json.dumps(rejected)
                yield json.dumps(fill_event)
                await self.release.wait()

            return iterate()

    class FakeConnection:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    socket = FakeSocket()
    monkeypatch.setattr(
        C.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnection(socket),
    )

    class Sink:
        async def emit_async(self, _envelope: C.TickEnvelope) -> None:
            raise AssertionError("rejected subscription must not emit userFills")

    async def scenario() -> None:
        starts: dict[str, int] = {}
        attempts: dict[str, list[dict[str, object]]] = {}
        attempts_dropped: dict[str, int] = {}
        diagnostics: dict[str, int] = {}
        live_ids: dict[str, set[str]] = {address: set()}
        live_counts: dict[str, int] = {address: 0}
        unclassified: dict[str, int] = {address: 0}
        reconnects: dict[str, int] = {address: 0}
        task = asyncio.create_task(
            C._socket_group(
                [address],
                Sink(),
                observation_start_ms=starts,
                live_ids=live_ids,
                live_fill_counts=live_counts,
                unclassified_fill_counts=unclassified,
                reconnect_counts=reconnects,
                l2_request_queue=asyncio.Queue(),
                l2_known_coins=set(),
                subscription_attempts=attempts,
                subscription_attempts_dropped=attempts_dropped,
                subscription_diagnostics=diagnostics,
            )
        )
        try:
            for _ in range(100):
                if diagnostics.get("rejected_acks") == 1:
                    break
                await asyncio.sleep(0.01)
            assert attempts[address][0]["status"] == "REJECTED"
            assert starts == {}
            assert live_counts[address] == 0
            assert live_ids[address] == set()
            assert diagnostics["messages_before_ack_dropped"] == 1
        finally:
            socket.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_userfills_disconnect_before_ack_is_invalidated_on_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    address = "0x" + "e" * 40
    ack = {
        "channel": "subscriptionResponse",
        "data": {
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": address},
        },
    }

    class FakeSocket:
        def __init__(self, *, disconnect: bool = False) -> None:
            self.disconnect = disconnect
            self.release = asyncio.Event()

        async def send(self, _payload: str) -> None:
            return None

        def __aiter__(self):
            async def iterate():
                if not self.disconnect:
                    yield json.dumps(ack)
                if self.disconnect:
                    raise ConnectionError("disconnected before subscription ack")
                await self.release.wait()

            return iterate()

    class FakeConnection:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    first = FakeSocket(disconnect=True)
    second = FakeSocket()
    sockets = iter([first, second])
    monkeypatch.setattr(
        C.websockets,
        "connect",
        lambda *_args, **_kwargs: FakeConnection(next(sockets)),
    )

    class Sink:
        async def emit_async(self, _envelope: C.TickEnvelope) -> None:
            return None

    async def scenario() -> None:
        starts: dict[str, int] = {}
        attempts: dict[str, list[dict[str, object]]] = {}
        dropped: dict[str, int] = {}
        diagnostics: dict[str, int] = {}
        live_ids: dict[str, set[str]] = {address: set()}
        live_counts: dict[str, int] = {address: 0}
        unclassified: dict[str, int] = {address: 0}
        reconnects: dict[str, int] = {address: 0}
        task = asyncio.create_task(
            C._socket_group(
                [address],
                Sink(),
                observation_start_ms=starts,
                live_ids=live_ids,
                live_fill_counts=live_counts,
                unclassified_fill_counts=unclassified,
                reconnect_counts=reconnects,
                l2_request_queue=asyncio.Queue(),
                l2_known_coins=set(),
                subscription_attempts=attempts,
                subscription_attempts_dropped=dropped,
                subscription_diagnostics=diagnostics,
            )
        )
        try:
            for _ in range(400):
                history = attempts.get(address, [])
                if len(history) >= 2 and history[1].get("status") == "ACTIVE":
                    break
                await asyncio.sleep(0.01)
            history = attempts[address]
            assert len(history) == 2
            assert history[0]["status"] == "INVALIDATED"
            assert history[1]["status"] == "ACTIVE"
            assert diagnostics["invalidated_on_disconnect"] == 1
            assert diagnostics["acknowledged"] == 1
            assert address in starts
            assert live_counts[address] == 0
        finally:
            second.release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_reconcile_timeout_is_unavailable_not_matched(monkeypatch) -> None:
    address = "0x" + "7" * 40

    async def slow_backfill(*_args, **_kwargs):
        await asyncio.sleep(1.0)
        return [], {"status": "COMPLETE"}

    monkeypatch.setattr(C, "exact_window_backfill", slow_backfill)
    monkeypatch.setattr(C, "RECONCILIATION_PER_VAULT_TIMEOUT_S", 0.01)

    async def scenario() -> None:
        result = await C.reconcile_forward_window(
            [address],
            start_ms_by_vault={address: 10_000},
            end_ms=20_000,
            live_ids={address: set()},
        )
        report = result[address]
        assert report["status"] == "UNAVAILABLE"
        assert report["audit"]["status"] == "PARTIAL"
        assert report["audit"]["reason"] == "REFERENCE_TIMEOUT"

    asyncio.run(scenario())

def test_broad_sweep_covers_complete_universe_in_one_compact_family() -> None:
    rows = [
        {"address": "0x" + f"{index + 20:040x}", "tvl_usd": 1000 + index}
        for index in range(4)
    ]

    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            address = body["user"]
            index = int(address[-2:], 16)
            return httpx.Response(
                200,
                json={
                    "marginSummary": {
                        "accountValue": "1000",
                        "totalNtlPos": "100",
                        "totalRawUsd": "900",
                        "totalMarginUsed": "10",
                    },
                    "assetPositions": [
                        {
                            "position": {
                                "coin": "BTC",
                                "szi": str(index),
                                "positionValue": "100",
                                "entryPx": "100",
                                "unrealizedPnl": "1",
                                "leverage": {"value": 2},
                            }
                        }
                    ],
                    "time": 1_700_000_000_000 + index,
                },
            )

        client = httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(handler),
        )

        class Sink:
            def __init__(self):
                self.rows = []

            def emit(self, envelope):
                self.rows.append(envelope)

        sink = Sink()
        result = await C.collect_broad_state(
            rows,
            sink,
            phase="START",
            request_interval_s=0.0,
            http_client=client,
        )
        await client.aclose()
        assert result["requested"] == 4
        assert result["observed"] == 4
        assert result["failed"] == 0
        assert len(sink.rows) == 4
        assert {row.instrument for row in sink.rows} == {"*"}
        assert {row.channel for row in sink.rows} == {"copy_vault_broad_state"}
        assert all(
            row.parsed_summary["position_fingerprint"]
            for row in sink.rows
        )

    asyncio.run(scenario())


def test_two_speed_ws_selection_never_exceeds_user_limit_and_rotates() -> None:
    rows = [
        {
            "address": "0x" + f"{index + 100:040x}",
            "tvl_usd": float(10_000 - index),
        }
        for index in range(20)
    ]
    states = {}
    for index, row in enumerate(rows):
        address = row["address"]
        states[address] = {
            "vault": address,
            "n_positions": 1 if index < 12 else 0,
            "expo_brute_usd": float(50_000 - index * 100),
            "position_fingerprint": f"{index:064x}",
        }

    selected_a = C.select_priority_ws_vaults(
        rows,
        {"states": states},
        max_ws_vaults=10,
        rotation_seed="run-a",
    )
    selected_b = C.select_priority_ws_vaults(
        rows,
        {"states": states},
        max_ws_vaults=10,
        rotation_seed="run-b",
    )

    assert len(selected_a) == 10
    assert C.validate_user_subscription_budget(
        [row["address"] for row in selected_a]
    ) == 10
    assert sum(row["ws_selection_reason"] == "ACTIVE_PRIORITY" for row in selected_a) == 8
    assert {
        row["address"] for row in selected_a if row["ws_selection_reason"] == "AUDIT_ROTATION"
    } != {
        row["address"] for row in selected_b if row["ws_selection_reason"] == "AUDIT_ROTATION"
    }




def test_selection_snapshot_declares_receive_clock_without_exchange_clock():
    selection = {
        "selected_at_ms": 1600,
        "source": "https://api.hyperliquid.xyz/info",
        "filters": {},
    }
    envelope = C.selection_envelope({"address": "0x" + "4" * 40}, selection)
    assert envelope.exchange_ts_ms is None
    assert envelope.received_ts_ms == 1600
    assert envelope.local_monotonic_ns is not None
    assert envelope.provenance["timestamp_semantics"] == "receive_observation_time_only"



def test_copy_vault_async_sink_waits_for_writer_instead_of_dropping():
    import asyncio
    from types import SimpleNamespace

    class Writer:
        def __init__(self):
            self.rows = []

        def append_batch_records(self, batch):
            self.rows.extend(batch)
            return batch

    async def verify():
        writer = Writer()
        sink = C.AsyncTickSink(writer, max_queue=1, batch_size=1)
        a = SimpleNamespace(source_id="vault", channel="copy_vault_fills", instrument="A")
        b = SimpleNamespace(source_id="vault", channel="copy_vault_fills", instrument="B")
        await sink.emit_async(a)
        pending = asyncio.create_task(sink.emit_async(b))
        await asyncio.sleep(0)
        assert sink.backpressure_events == 1
        assert not pending.done()
        worker = asyncio.create_task(sink.run())
        await pending
        await sink.close()
        await worker
        assert sink.drops == {}
        assert sink.accepted == sink.persisted == 2
        assert writer.rows == [a, b]

    asyncio.run(verify())


def test_accounting_history_backfill_preserves_official_nested_rest_shape() -> None:
    vault = "0x" + "4" * 40
    event = {
        "time": 2_000,
        "hash": "0xfunding-event",
        "delta": {
            "coin": "BTC",
            "fundingRate": "0.0001",
            "szi": "0.25",
            "usdc": "-0.75",
            "type": "funding",
        },
    }

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, object]]:
            return [event]

    class Client:
        calls: list[dict[str, object]] = []

        async def post(self, path: str, *, json: dict[str, object]) -> Response:
            assert path == "/info"
            self.calls.append(json)
            return Response()

    client = Client()
    rows, audit = asyncio.run(C.exact_window_accounting_backfill(
        client,
        vault,
        request_type="userFunding",
        start_ms=1_000,
        end_ms=3_000,
    ))

    assert rows == [event]
    assert audit["status"] == "COMPLETE"
    assert audit["event_count"] == 1
    assert audit["proof_of_pnl_allowed"] is False
    assert audit["empty_result_is_zero_pnl_proof"] is False
    assert client.calls == [{
        "type": "userFunding",
        "user": vault,
        "startTime": 1_000,
        "endTime": 3_000,
    }]

    [envelope] = C.rest_accounting_backfill_envelopes(
        rows,
        vault=vault,
        request_type="userFunding",
        audit=audit,
        receive_wall_ms=4_000,
        receive_mono_ns=10,
    )
    assert envelope.source_id == "hl_public_account_backfill"
    assert envelope.channel == "copy_vault_funding"
    assert envelope.exchange_ts_ms == 2_000
    assert envelope.provenance["transport"] == "https"
    assert envelope.provenance["historical_only"] is True
    assert envelope.parsed_summary["proof_of_pnl_allowed"] is False
    assert envelope.raw_payload["data"]["fundings"] == [event]


def test_accounting_history_full_page_at_minimum_window_remains_partial() -> None:
    vault = "0x" + "5" * 40
    rows = [
        {
            "time": 2_000,
            "hash": f"0xledger-{index}",
            "delta": {"type": "deposit", "usdc": "1"},
        }
        for index in range(C.MAX_TIME_RANGE_RESPONSE_ROWS)
    ]

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, object]]:
            return rows

    class Client:
        async def post(self, path: str, *, json: dict[str, object]) -> Response:
            assert json["type"] == "userNonFundingLedgerUpdates"
            return Response()

    events, audit = asyncio.run(C.exact_window_accounting_backfill(
        Client(),
        vault,
        request_type="userNonFundingLedgerUpdates",
        start_ms=1_000,
        end_ms=2_000,
        min_window_ms=1_000,
    ))
    assert len(events) == C.MAX_TIME_RANGE_RESPONSE_ROWS
    assert audit["status"] == "PARTIAL"
    assert audit["cap_blocked_windows"] == [{
        "start_ms": 1_000,
        "end_ms": 2_000,
        "rows": C.MAX_TIME_RANGE_RESPONSE_ROWS,
        "cap": C.MAX_TIME_RANGE_RESPONSE_ROWS,
    }]
    assert audit["empty_result_is_zero_pnl_proof"] is False


def test_historical_accounting_backfills_are_wired_into_campaign_report(monkeypatch) -> None:
    vault = "0x" + "6" * 40
    selection_ms = 2_000_000_000_000

    class Response:
        def __init__(self, payload: object) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self.payload

    class Client:
        def __init__(self, **kwargs: object) -> None:
            self.options = kwargs
            clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path: str, *, json: dict[str, object]) -> Response:
            assert path == "/info"
            if json["type"] == "userFunding":
                return Response([{
                    "time": selection_ms - 1,
                    "hash": "0xfunding",
                    "delta": {
                        "coin": "BTC", "usdc": "0.1", "szi": "1",
                        "fundingRate": "0.0001",
                    },
                }])
            assert json["type"] == "userNonFundingLedgerUpdates"
            return Response([{
                "time": selection_ms - 1,
                "hash": "0xledger",
                "delta": {"type": "deposit", "usdc": "1"},
            }])

    async def no_fill_backfill(client, address, **kwargs):
        return [], {
            "status": "COMPLETE",
            "requested_start_ms": kwargs["start_ms"],
            "requested_end_ms": kwargs["end_ms"],
            "rows": 0,
            "requests": 1,
            "pending_windows": 0,
            "request_budget_exhausted": False,
            "invalid_fill_count": 0,
            "failed_windows": [],
            "cap_blocked_windows": [],
            "retention_cap_reached": False,
        }

    clients = []
    monkeypatch.setattr(C.httpx, "AsyncClient", Client)
    monkeypatch.setattr(C, "exact_window_backfill", no_fill_backfill)
    reports, envelopes = asyncio.run(C.collect_historical_backfills(
        [vault], selection_ts_ms=selection_ms, lookback_hours=1,
    ))

    report = reports[vault]
    accounting = report["accounting_backfill"]
    assert accounting["copy_vault_funding"]["status"] == "COMPLETE"
    assert accounting["copy_vault_ledger"]["status"] == "COMPLETE"
    assert {event.channel for event in envelopes} == {
        "copy_vault_funding", "copy_vault_ledger",
    }
    assert all(event.source_id == "hl_public_account_backfill" for event in envelopes)
    assert all(event.provenance["historical_only"] is True for event in envelopes)
    assert all(event.parsed_summary["proof_of_pnl_allowed"] is False for event in envelopes)
    assert clients[0].options == {
        "base_url": "https://api.hyperliquid.xyz",
        "timeout": 15.0,
    }


def test_historical_accounting_shard_is_replay_safe_but_not_pnl_proof(tmp_path: Path) -> None:
    vault = "0x" + "7" * 40
    raw_root = tmp_path / "raw"
    output = tmp_path / "bundle"
    writer = C.PartitionedTickDatasetWriter(
        raw_root, rotate_bytes=10_000_000, flush_every=1,
    )
    audit = {
        "request_type": "userFunding",
        "status": "COMPLETE",
        "requested_start_ms": 1_000,
        "requested_end_ms": 2_000,
        "event_count": 1,
        "proof_of_pnl_allowed": False,
        "forward_evidence_allowed": False,
    }
    [envelope] = C.rest_accounting_backfill_envelopes(
        [{
            "time": 2_000,
            "hash": "0xfunding",
            "delta": {
                "coin": "BTC", "usdc": "0.1", "szi": "1",
                "fundingRate": "0.0001",
            },
        }],
        vault=vault,
        request_type="userFunding",
        audit=audit,
        receive_wall_ms=3_000,
        receive_mono_ns=123,
    )
    writer.append(envelope)
    writer.rotate_all()
    index = C.build_copy_vault_bundle(
        raw_root,
        output,
        collector_version="a" * 40,
        reconciliation={},
        queue_drops={},
        selection={"selected_at_ms": 3_000},
        collection_run_id="accounting-history-test",
        historical_backfill={vault: {
            "accounting_backfill": {"copy_vault_funding": audit},
        }},
    )
    assert index["shard_count"] == 1
    [manifest_path] = (output / "manifests").glob("*.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["reconciliation"]["status"] == "SNAPSHOT_VERIFIED"
    assert manifest["copy_vault_selection"]["historical_only"] is True
    assert manifest["proof_of_pnl_allowed"] is False
    assert manifest["reconciliation"]["forward_evidence_allowed"] is False
