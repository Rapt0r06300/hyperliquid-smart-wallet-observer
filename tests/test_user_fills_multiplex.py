"""V27 — firehose userFills MULTIPLEXE: chunking/dedupe/caps (pur), garde network-read,
fan-out parallele de connexions, store des fills frais. Fakes only (no network, no DB).
Read-only / paper-only."""

from __future__ import annotations

import asyncio
import json

import hl_observer.wallets.user_fills_live as ufl
from hl_observer.config.settings import Settings
from hl_observer.wallets.user_fills_multiplex import (
    HL_MAX_WALLETS_PER_CONNECTION,
    MAX_CONNECTIONS_HARD,
    plan_multiplex_chunks,
    stream_user_fills_multiplex,
)


def _wallet(i: int) -> str:
    return "0x" + f"{i:040x}"


def _msg(wallet: str, is_snapshot: bool, fills: list[dict]) -> str:
    return json.dumps({"channel": "userFills", "data": {"user": wallet, "isSnapshot": is_snapshot, "fills": fills}})


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
        raise RuntimeError("ws closed")            # termine la boucle interne -> reconnect


# --------------------------------------------------------------------- chunking (pur)

def test_chunking_splits_by_ten():
    chunks = plan_multiplex_chunks([_wallet(i) for i in range(1, 26)], wallets_per_connection=10, max_connections=4)
    assert [len(c) for c in chunks] == [10]


def test_chunking_capped_by_max_connections():
    chunks = plan_multiplex_chunks([_wallet(i) for i in range(1, 101)], wallets_per_connection=10, max_connections=3)
    assert len(chunks) == 1 and sum(len(c) for c in chunks) == 10


def test_chunking_hard_cap_on_connections():
    chunks = plan_multiplex_chunks([_wallet(i) for i in range(1, 200)], wallets_per_connection=1, max_connections=999)
    assert len(chunks) == MAX_CONNECTIONS_HARD
    assert sum(len(chunk) for chunk in chunks) == 10


def test_chunking_dedupes_and_validates():
    raw = [_wallet(1), _wallet(1).upper(), "pas-une-adresse", _wallet(2), ""]
    chunks = plan_multiplex_chunks(raw, wallets_per_connection=10, max_connections=4)
    assert chunks == [[_wallet(1), _wallet(2)]]        # doublon + invalides ecartes


# ------------------------------------------------------------------- streaming (fakes)

def test_network_read_guard():
    res = asyncio.run(stream_user_fills_multiplex(
        Settings(), wallets=[_wallet(1)], session_factory=lambda: None, network_read=False))
    assert res.stopped_reason == "NETWORK_READ_DISABLED"
    assert res.connections == 0


def test_no_wallets_is_source_unavailable():
    res = asyncio.run(stream_user_fills_multiplex(
        Settings(), wallets=["nope"], session_factory=lambda: None, network_read=True,
        websocket_connect=lambda url: _FakeWS([]), sleep=lambda s: asyncio.sleep(0)))
    assert res.stopped_reason == "SOURCE_UNAVAILABLE"


def test_opens_one_connection_per_chunk():
    calls = {"n": 0}

    def fake_connect(url):
        calls["n"] += 1
        return _FakeWS([])                             # ferme aussitot -> 1 connect / chunk

    res = asyncio.run(stream_user_fills_multiplex(
        Settings(), wallets=[_wallet(i) for i in range(1, 26)], session_factory=lambda: None,
        network_read=True, max_connections=4, wallets_per_connection=3,
        websocket_connect=fake_connect,
        max_reconnects=0, sleep=lambda s: asyncio.sleep(0)))
    assert res.connections == 4
    assert res.wallets_covered == 10
    assert calls["n"] == 4 and res.total_connects == 4
    assert res.stopped_reason == "max_reconnects"


def test_fresh_fills_stored_across_multiplex(monkeypatch):
    stored = []

    def fake_store(session_factory, wallet, fills, *, max_live_fill_age_ms, stats):
        stored.append(wallet)
        stats.fresh_fills_stored += len(fills)

    monkeypatch.setattr(ufl, "_store_fresh_fills", fake_store)

    def fake_connect(url):
        # chaque connexion pousse un fill FRAIS pour les 2 wallets qu'elle suit
        return _FakeWS([
            _msg(_wallet(1), False, [{"coin": "BTC", "time": 123, "px": "60000"}]),
            _msg(_wallet(2), False, [{"coin": "ETH", "time": 124, "px": "3000"}]),
        ])

    res = asyncio.run(stream_user_fills_multiplex(
        Settings(), wallets=[_wallet(1), _wallet(2)], session_factory=lambda: None,
        network_read=True, wallets_per_connection=10, max_connections=1,
        websocket_connect=fake_connect, max_reconnects=0, sleep=lambda s: asyncio.sleep(0)))
    assert res.fresh_fills_stored >= 2
    assert set(stored) == {_wallet(1), _wallet(2)}
