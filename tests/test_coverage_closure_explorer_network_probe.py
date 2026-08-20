from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import hl_observer.explorer.explorer_network_probe as probe
from hl_observer.explorer.explorer_models import ExplorerSourceStatus, ExplorerTransaction


def _tx(hash_: str | None, wallet: str | None, *, block=1, ts=2, action="trade") -> ExplorerTransaction:
    return ExplorerTransaction(
        tx_hash=hash_, wallet_address=wallet, block=block, timestamp_ms=ts,
        action_type=action, validation_status=ExplorerSourceStatus.FULL_ADDRESS_OK,
    )


def test_probe_dry_run_is_network_free() -> None:
    result = asyncio.run(probe.probe_explorer_network(dry_run=True, url="https://example.test"))
    assert result.status == ExplorerSourceStatus.IMPORT_REQUIRED
    assert result.finished_at_ms is not None
    assert result.endpoints_found[0].endpoint_url == "https://example.test"
    assert result.endpoints_found[0].status == ExplorerSourceStatus.IMPORT_REQUIRED
    assert "dry_run_no_network" in result.notes


def test_probe_stream_success_adds_block_details_and_dedupes(monkeypatch) -> None:
    tx1 = _tx("h1", "0xA")
    tx1_dup = _tx("h1", "0xA")
    tx2 = _tx("h2", "0xB")
    async def stream(**kwargs):
        return [tx1, tx1_dup], 2, [10, 10, 11]
    async def blocks(heights, **kwargs):
        assert heights == [10, 10]
        return [tx2], 1
    monkeypatch.setattr(probe, "_read_explorer_stream", stream)
    monkeypatch.setattr(probe, "_read_block_details", blocks)
    result = asyncio.run(probe.probe_explorer_network(dry_run=False, max_events=5))
    assert result.status == ExplorerSourceStatus.OK
    assert [tx.tx_hash for tx in result.transactions] == ["h1", "h2"]
    assert result.events_seen == 2
    assert result.full_addresses_found == 2
    assert result.truncated_addresses_rejected == 3
    assert result.candidates_created == 2
    assert [ep.method for ep in result.endpoints_found] == ["WEBSOCKET", "POST"]


def test_probe_stream_success_without_wallet_is_import_required(monkeypatch) -> None:
    async def stream(**kwargs):
        return [_tx("h", None)], 0, []
    monkeypatch.setattr(probe, "_read_explorer_stream", stream)
    result = asyncio.run(probe.probe_explorer_network(dry_run=False, max_events=1))
    assert result.status == ExplorerSourceStatus.IMPORT_REQUIRED
    assert result.full_addresses_found == 0
    assert "aucune adresse" in result.notes[-1]


class _Response:
    def __init__(self, *, text="", payload=None, url="https://fallback.test", status=200, success=True):
        self.text = text
        self._payload = payload
        self.url = url
        self.status_code = status
        self.is_success = success
    def raise_for_status(self):
        if not self.is_success:
            raise httpx.HTTPStatusError("bad", request=httpx.Request("GET", self.url), response=httpx.Response(self.status_code))
    def json(self):
        return self._payload


class _AsyncClient:
    def __init__(self, response, *args, **kwargs):
        self.response = response
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def get(self, *args, **kwargs): return self.response
    async def post(self, *args, **kwargs): return self.response


def test_probe_stream_failure_http_fallback_success(monkeypatch) -> None:
    async def stream(**kwargs):
        raise OSError("ws down")
    monkeypatch.setattr(probe, "_read_explorer_stream", stream)
    response = _Response(text="payload")
    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda *a, **k: _AsyncClient(response))
    monkeypatch.setattr(probe, "parse_explorer_payload", lambda payload, source_url: ([_tx("h", "0xA")], 4))
    result = asyncio.run(probe.probe_explorer_network(dry_run=False))
    assert result.status == ExplorerSourceStatus.OK
    assert result.full_addresses_found == 1
    assert result.truncated_addresses_rejected == 4
    assert any(note.startswith("rpc_stream_failed=") for note in result.notes)
    assert result.endpoints_found[0].http_status == 200


def test_probe_stream_failure_http_fallback_failure(monkeypatch) -> None:
    async def stream(**kwargs):
        raise TimeoutError("ws timeout")
    monkeypatch.setattr(probe, "_read_explorer_stream", stream)
    class FailingClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("offline", request=httpx.Request("GET", "https://x"))
    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda *a, **k: FailingClient())
    result = asyncio.run(probe.probe_explorer_network(dry_run=False))
    assert result.status == ExplorerSourceStatus.NETWORK_FAILED
    assert "offline" in result.error_message
    assert "source_failed_visible_no_wallet_invented" in result.notes


class _WS:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def send(self, value): self.sent.append(json.loads(value))
    async def recv(self):
        try:
            value = next(self.messages)
        except StopIteration:
            await asyncio.sleep(10)
        if value is TimeoutError:
            await asyncio.sleep(10)
        return value


def test_read_explorer_stream_parses_blocks_txs_and_ignores_noise(monkeypatch) -> None:
    messages = [
        "not json",
        json.dumps({"channel": "subscriptionResponse"}),
        json.dumps({"other": 1}),
        json.dumps([{"height": 100, "numTxs": 2}, {"height": 101, "numTxs": 1}]),
        json.dumps([{"kind": "tx"}, "ignored"]),
    ]
    ws = _WS(messages)
    class Conn:
        def __init__(self, ws): self.ws = ws
        async def __aenter__(self): return self.ws
        async def __aexit__(self, *args): return False
    monkeypatch.setattr(probe.websockets, "connect", lambda *a, **k: Conn(ws))
    monkeypatch.setattr(probe, "parse_explorer_records", lambda records, source_url: ([_tx("h", "0xA")], 3))
    original_wait_for = asyncio.wait_for
    calls = {"n": 0}
    async def bounded(awaitable, timeout):
        calls["n"] += 1
        if calls["n"] > len(messages):
            if hasattr(awaitable, "close"): awaitable.close()
            raise asyncio.TimeoutError
        return await original_wait_for(awaitable, timeout=0.1)
    monkeypatch.setattr(probe.asyncio, "wait_for", bounded)
    txs, rejected, heights = asyncio.run(probe._read_explorer_stream(timeout_seconds=0.01, max_events=1))
    assert [tx.tx_hash for tx in txs] == ["h"]
    assert rejected == 3
    assert heights == [100, 101]
    assert [item["subscription"]["type"] for item in ws.sent] == ["explorerBlock", "explorerTxs"]


def test_read_block_details_stops_at_limit_and_slices(monkeypatch) -> None:
    responses = [_Response(payload={"height": 1}), _Response(payload={"height": 2})]
    class Client:
        def __init__(self, *a, **k): self.index = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def post(self, url, **kwargs):
            response = responses[self.index]
            self.index += 1
            return response
    monkeypatch.setattr(probe.httpx, "AsyncClient", Client)
    monkeypatch.setattr(probe, "parse_explorer_payload", lambda payload, source_url: ([_tx(f"h{payload['height']}a", "0xA"), _tx(f"h{payload['height']}b", "0xB")], 1))
    txs, rejected = asyncio.run(probe._read_block_details([1, 2], timeout_seconds=1, max_events=3))
    assert [tx.tx_hash for tx in txs] == ["h1a", "h1b", "h2a"]
    assert rejected == 2


def test_dedupe_transaction_hash_and_fallback_key() -> None:
    rows = [
        _tx("h1", "0xA"), _tx("h1", "0xB"),
        _tx(None, "0xA", block=1, ts=2, action="x"),
        _tx(None, "0xA", block=1, ts=2, action="x"),
        _tx(None, "0xA", block=2, ts=2, action="x"),
    ]
    deduped = probe._dedupe_transactions(rows)
    assert len(deduped) == 3
    assert deduped[0].tx_hash == "h1"
