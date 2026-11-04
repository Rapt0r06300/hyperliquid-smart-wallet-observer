from __future__ import annotations

import asyncio
import json

import httpx

from hl_observer.collection import bitget_market_data as bitget
from hl_observer.collection.bitget_market_data import BitgetMarketState, BitgetPublicClient
from hl_observer.collection.native_venue_market import DESYNC, EXPLOITABLE, STALE, UNMEASURABLE


def _book(
    *,
    seq: int | None = 1,
    action: str = "snapshot",
    channel: str = "books",
    inst_type: str = "USDT-FUTURES",
    **extra,
) -> dict:
    item = {
        "seq": seq,
        "ts": "1700000000000",
        "bids": [["100", "1"]],
        "asks": [["101", "1"]],
    }
    item.update(extra.pop("item", {}))
    payload = {
        "action": action,
        "arg": {"instType": inst_type, "channel": channel, "instId": "BTCUSDT"},
        "data": [item],
    }
    payload.update(extra)
    return payload


def test_bug091_snapshot_action_reanchors_after_delta_and_missing_seq_fails_closed() -> None:
    state = BitgetMarketState("BTCUSDT")
    assert state.apply(_book(seq=10)) == EXPLOITABLE
    delta = _book(seq=11, action="update", item={"pseq": 10, "bids": [["99", "2"]], "asks": []})
    assert state.apply(delta) == EXPLOITABLE
    assert 99.0 in state.bids
    assert state.apply(_book(seq=1, action="snapshot", item={"bids": [["110", "1"]], "asks": [["111", "1"]]})) == EXPLOITABLE
    assert 99.0 not in state.bids
    assert state.apply(_book(seq=None, action="snapshot")) == UNMEASURABLE
    assert state.reason == "MISSING_SNAPSHOT_SEQUENCE"


def test_bug092_zero_numeric_fields_are_not_reused_as_stale_values() -> None:
    state = BitgetMarketState("BTCUSDT")
    assert state.apply(_book(item={"lastPr": "12", "holdingAmount": "7"})) == EXPLOITABLE
    assert state.apply(_book(seq=2, item={"lastPr": "0", "holdingAmount": "0"})) == EXPLOITABLE
    assert state.last == 0
    assert state.open_interest == 0


def test_bug093_checksum_claim_without_checksum_is_not_verified() -> None:
    state = BitgetMarketState("BTCUSDT")
    payload = _book(item={"checksum_verified": True})
    assert state.apply(payload) == UNMEASURABLE
    assert state.reason == "CHECKSUM_MISSING"
    assert not state.bids and not state.asks


def test_bug094_wrong_bitget_instrument_type_is_rejected() -> None:
    state = BitgetMarketState("BTCUSDT")
    assert state.apply(_book(inst_type="SPOT")) == DESYNC
    assert state.reason == "INST_TYPE_MISMATCH"
    payload = {"data": [{"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT", "productType": "SPOT"}]}
    assert bitget.parse_bitget_instruments(payload) == []


def test_bug095_safe_usdt_symbol_uses_declared_base_without_alias_collision() -> None:
    valid = {"symbol": "SAFEUSDT", "baseCoin": "SAFE", "quoteCoin": "USDT", "symbolStatus": "normal"}
    wrong = {"symbol": "SAFEUSDT", "baseCoin": "SAFE2", "quoteCoin": "USDT", "symbolStatus": "normal"}
    assert bitget.parse_bitget_instruments({"data": [valid, wrong]}) == [("SAFE", "SAFEUSDT")]


def test_bug096_stale_book_is_reported_at_snapshot_boundary() -> None:
    state = BitgetMarketState("BTCUSDT", stale_after_ms=1_000)
    assert state.apply(_book(item={"ts": "1000"}), receive_ts_ms=1_000) == EXPLOITABLE
    assert state.snapshot(now_ms=3_001).quality == STALE


def test_bug097_bitget_app_ping_is_sent_when_socket_is_idle(monkeypatch) -> None:
    sent: list[str] = []

    class Socket:
        async def send(self, value: str) -> None:
            sent.append(value)

        async def recv(self):
            if not hasattr(self, "calls"):
                self.calls = 0
            self.calls += 1
            if self.calls == 1:
                return json.dumps({"arg": {"channel": "trades", "instId": "BTCUSDT"}, "data": []})
            if self.calls == 2:
                raise asyncio.TimeoutError
            raise asyncio.CancelledError

    socket = Socket()

    class Connector:
        async def __aenter__(self):
            return socket

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(bitget.websockets, "connect", lambda *args, **kwargs: Connector())

    async def run() -> None:
        stream = BitgetPublicClient()._classic_messages(("BTCUSDT",))
        await stream.__anext__()
        try:
            await stream.__anext__()
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert "ping" in sent


def test_bug098_trades_channel_never_becomes_an_l2_book() -> None:
    state = BitgetMarketState("BTCUSDT")
    payload = {"arg": {"instType": "USDT-FUTURES", "channel": "trades", "instId": "BTCUSDT"}, "data": [{"bids": [["100", "1"]], "asks": [["101", "1"]]}]}
    assert state.apply(payload) == UNMEASURABLE
    assert not state.bids and not state.asks


def test_bug099_rate_limit_is_retried_with_bounded_backoff(monkeypatch) -> None:
    calls = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(bitget.time, "sleep", lambda _: None)
    client = BitgetPublicClient()
    with httpx.Client(transport=httpx.MockTransport(responder)) as http_client:
        assert client._get_json_with_retry(http_client, "https://example.test") == {"ok": True}
    assert calls == 2


def test_bug100_classic_stream_reconnects_after_bounded_session(monkeypatch) -> None:
    connections = 0

    class Socket:
        def __init__(self, serial: int) -> None:
            self.serial = serial
            self.done = False

        async def send(self, value: str) -> None:
            return None

        async def recv(self):
            if not self.done:
                self.done = True
                return json.dumps({"arg": {"channel": "trades", "instId": "BTCUSDT"}, "data": [{"serial": self.serial}]})
            raise asyncio.CancelledError

    class Connector:
        def __init__(self, socket: Socket) -> None:
            self.socket = socket

        async def __aenter__(self):
            return self.socket

        async def __aexit__(self, *_):
            return False

    def connect(*args, **kwargs):
        nonlocal connections
        connections += 1
        return Connector(Socket(connections))

    monkeypatch.setattr(bitget.websockets, "connect", connect)

    async def run() -> list[dict]:
        client = BitgetPublicClient()
        client.session_refresh_s = 0
        stream = client._classic_messages(("BTCUSDT",))
        first = await stream.__anext__()
        second = await stream.__anext__()
        await stream.aclose()
        return [first, second]

    rows = asyncio.run(run())
    assert [row["data"][0]["serial"] for row in rows] == [1, 2]
    assert connections == 2
