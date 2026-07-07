"""V16 — persistent userFills WS stream: snapshot-ignore, fresh-fill store, reconnect/backoff,
network-read guard. Uses fakes (no network, no DB). Read-only / paper-only."""

from __future__ import annotations

import asyncio
import json
import pytest

from hl_observer.config.settings import Settings
import hl_observer.wallets.user_fills_live as ufl
from hl_observer.wallets.user_fills_live import stream_user_fills_ws

W = "0x" + "a" * 40


def _msg(is_snapshot, fills):
    return json.dumps({"channel": "userFills", "data": {"user": W, "isSnapshot": is_snapshot, "fills": fills}})


class _FakeWS:
    def __init__(self, messages):
        self._msgs = list(messages)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def send(self, m):
        return None
    async def recv(self):
        if self._msgs:
            return self._msgs.pop(0)
        raise RuntimeError("ws closed")            # ends inner loop -> triggers reconnect


def test_network_read_guard():
    res = asyncio.run(stream_user_fills_ws(Settings(), wallets=[W], session_factory=lambda: None,
                                           network_read=False))
    assert res.stopped_reason == "NETWORK_READ_DISABLED"


def test_snapshot_ignored_and_reconnect_bounded(monkeypatch):
    calls = []
    monkeypatch.setattr(ufl, "_store_fresh_fills", lambda *a, **k: calls.append(("store", a, k)))
    # every connection yields one SNAPSHOT message (must be ignored), then closes -> reconnect
    def fake_connect(url):
        return _FakeWS([_msg(True, [{"coin": "ETH", "time": 1, "px": "1"}])])
    res = asyncio.run(stream_user_fills_ws(
        Settings(), wallets=[W], session_factory=lambda: None, network_read=True,
        websocket_connect=fake_connect, max_reconnects=2, sleep=lambda s: asyncio.sleep(0),
    ))
    assert res.connects >= 2 and res.reconnects >= 1
    assert res.snapshots_ignored >= 1
    assert res.stopped_reason == "max_reconnects"
    assert calls == []                              # snapshots never stored (we want FRESH only)


def test_fresh_fill_is_stored(monkeypatch):
    stored = []
    def fake_store(session_factory, wallet, fills, *, max_live_fill_age_ms, stats):
        stored.append((wallet, [f.get("coin") for f in fills])); stats.fresh_fills_stored += len(fills)
    monkeypatch.setattr(ufl, "_store_fresh_fills", fake_store)
    def fake_connect(url):
        return _FakeWS([_msg(False, [{"coin": "BTC", "time": 123, "px": "60000"}])])
    res = asyncio.run(stream_user_fills_ws(
        Settings(), wallets=[W], session_factory=lambda: None, network_read=True,
        websocket_connect=fake_connect, max_reconnects=0, sleep=lambda s: asyncio.sleep(0),
    ))
    assert stored and stored[0][0] == W and "BTC" in stored[0][1]
    assert res.fresh_fills_stored >= 1
