from __future__ import annotations

import asyncio
import json

import httpx

from hl_observer.explorer import explorer_network_probe as probe
from hl_observer.explorer.explorer_models import ExplorerSourceStatus, ExplorerTransaction


WALLET = "0x" + "1" * 40


def _tx(*, tx_hash: str | None = "0xabc", wallet: str | None = WALLET, block: int = 1) -> ExplorerTransaction:
    return ExplorerTransaction(
        tx_hash=tx_hash,
        block=block,
        timestamp_ms=10,
        action_type="fill",
        wallet_address=wallet,
        source_url="unit",
    )


def test_probe_explorer_dry_run_is_network_free() -> None:
    result = asyncio.run(probe.probe_explorer_network(dry_run=True, url="https://unit.invalid"))
    assert result.status == ExplorerSourceStatus.IMPORT_REQUIRED
    assert result.finished_at_ms is not None
    assert result.endpoints_found[0].endpoint_url == "https://unit.invalid"
    assert "dry_run_no_network" in result.notes


def test_probe_explorer_stream_and_block_details_success(monkeypatch) -> None:
    async def stream(**kwargs):
        assert kwargs["max_events"] == 5
        return [_tx(tx_hash="a")], 1, [100, 101, 100]

    async def blocks(heights, **kwargs):
        assert heights == [100, 101]
        assert kwargs["max_events"] == 4
        return [_tx(tx_hash="b", block=100)], 2

    monkeypatch.setattr(probe, "_read_explorer_stream", stream)
    monkeypatch.setattr(probe, "_read_block_details", blocks)
    result = asyncio.run(probe.probe_explorer_network(dry_run=False, max_events=5))
    assert result.status == ExplorerSourceStatus.OK
    assert result.events_seen == 2
    assert result.full_addresses_found == 1
    assert result.truncated_addresses_rejected == 3
    assert result.candidates_created == 1
    assert [item.method for item in result.endpoints_found] == ["WEBSOCKET", "POST"]


def test_probe_explorer_without_full_address_requests_import(monkeypatch) -> None:
    async def stream(**kwargs):
        return [_tx(wallet=None)], 0, []

    monkeypatch.setattr(probe, "_read_explorer_stream", stream)
    result = asyncio.run(probe.probe_explorer_network(dry_run=False, max_events=2))
    assert result.status == ExplorerSourceStatus.IMPORT_REQUIRED
    assert result.full_addresses_found == 0
    assert result.candidates_created == 0


class _Response:
    def __init__(self, *, status: int = 200, text: str = "payload", json_value=None) -> None:
        self.status_code = status
        self.is_success = 200 <= status < 300
        self.url = "https://fallback.invalid/final"
        self.text = text
        self._json_value = json_value if json_value is not None else {"ok": True}

    def raise_for_status(self) -> None:
        if not self.is_success:
            raise httpx.HTTPStatusError(
                "bad status",
                request=httpx.Request("GET", str(self.url)),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._json_value


class _Client:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response or _Response()
        self.error = error
        self.posts: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, *args, **kwargs):
        if self.error is not None:
            raise self.error
        return self.response

    async def post(self, url, *, json, headers):
        self.posts.append((url, json))
        if self.error is not None:
            raise self.error
        return self.response


def test_probe_explorer_falls_back_to_html_read(monkeypatch) -> None:
    async def fail_stream(**kwargs):
        raise OSError("ws offline")

    client = _Client(response=_Response())
    monkeypatch.setattr(probe, "_read_explorer_stream", fail_stream)
    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(probe, "parse_explorer_payload", lambda payload, source_url: ([_tx(tx_hash="fallback")], 4))
    result = asyncio.run(probe.probe_explorer_network(dry_run=False, max_events=3))
    assert result.status == ExplorerSourceStatus.OK
    assert result.events_seen == 1
    assert result.truncated_addresses_rejected == 4
    assert result.endpoints_found[0].http_status == 200
    assert any(note.startswith("rpc_stream_failed=") for note in result.notes)


def test_probe_explorer_fallback_failure_is_fail_closed(monkeypatch) -> None:
    async def fail_stream(**kwargs):
        raise OSError("ws offline")

    request = httpx.Request("GET", "https://fallback.invalid")
    client = _Client(error=httpx.ConnectError("http offline", request=request))
    monkeypatch.setattr(probe, "_read_explorer_stream", fail_stream)
    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda *args, **kwargs: client)
    result = asyncio.run(probe.probe_explorer_network(dry_run=False))
    assert result.status == ExplorerSourceStatus.NETWORK_FAILED
    assert "http offline" in str(result.error_message)
    assert "source_failed_visible_no_wallet_invented" in result.notes


class _FakeWs:
    def __init__(self, messages: list[str]) -> None:
        self.messages = list(messages)
        self.sent: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return self.messages.pop(0)


def test_read_explorer_stream_parses_protocol_branches(monkeypatch) -> None:
    messages = [
        "{bad-json",
        json.dumps({"channel": "subscriptionResponse"}),
        json.dumps({"not": "a list"}),
        json.dumps([{"height": 77, "numTxs": 1}]),
        json.dumps([{"kind": "tx"}]),
    ]
    ws = _FakeWs(messages)
    monkeypatch.setattr(probe.websockets, "connect", lambda *args, **kwargs: ws)
    monkeypatch.setattr(probe, "parse_explorer_records", lambda records, source_url: ([_tx(tx_hash="stream", block=77)], 2))
    transactions, rejected, heights = asyncio.run(probe._read_explorer_stream(timeout_seconds=2.0, max_events=1))
    assert len(transactions) == 1
    assert rejected == 2
    assert heights == [77]
    assert len(ws.sent) == 2
    assert "explorerBlock" in ws.sent[0]
    assert "explorerTxs" in ws.sent[1]


def test_read_block_details_obeys_max_events(monkeypatch) -> None:
    client = _Client(response=_Response(json_value={"block": True}))
    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda *args, **kwargs: client)
    calls: list[str] = []

    def parse(payload, source_url):
        calls.append(source_url)
        return ([_tx(tx_hash=source_url + "-1"), _tx(tx_hash=source_url + "-2")], 1)

    monkeypatch.setattr(probe, "parse_explorer_payload", parse)
    transactions, rejected = asyncio.run(probe._read_block_details([10, 11, 12], timeout_seconds=1.0, max_events=3))
    assert len(transactions) == 3
    assert rejected == 2
    assert len(client.posts) == 2
    assert client.posts[0][1] == {"type": "blockDetails", "height": 10}


def test_dedupe_transactions_uses_hash_and_fallback_key() -> None:
    rows = [
        _tx(tx_hash="same", block=1),
        _tx(tx_hash="same", block=2),
        _tx(tx_hash=None, wallet=WALLET, block=3),
        _tx(tx_hash=None, wallet=WALLET, block=3),
        _tx(tx_hash="unique", block=4),
    ]
    deduped = probe._dedupe_transactions(rows)
    assert [row.tx_hash for row in deduped] == ["same", None, "unique"]
