import asyncio
import json

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import Fill, PositionDeltaModel
from hl_observer.utils.time import now_ms
from hl_observer.wallets.user_fills_live import (
    scan_user_fills_ws,
    store_user_fills_live_result,
    user_fills_from_message,
)


WALLET = "0x" + "c" * 40


def _user_fill_message(*, snapshot: bool = False, fill_time_ms: int | None = None, fill_hash: str = "0xfill"):
    fill_time_ms = fill_time_ms if fill_time_ms is not None else now_ms()
    return json.dumps(
        {
            "channel": "userFills",
            "data": {
                "user": WALLET,
                "isSnapshot": snapshot,
                "fills": [
                    {
                        "coin": "BTC",
                        "dir": "Open Long",
                        "px": "100",
                        "sz": "1",
                        "fee": "0.01",
                        "time": fill_time_ms,
                        "hash": fill_hash,
                        "tid": 1,
                        "oid": 2,
                        "startPosition": "0",
                    }
                ],
            },
        }
    )


class FakeWs:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def send(self, payload):
        self.sent.append(payload)

    async def recv(self):
        if self.messages:
            return self.messages.pop(0)
        await asyncio.sleep(2)
        return "{}"


def test_user_fills_parser_extracts_wallet_and_ignores_snapshot_flag():
    wallet, is_snapshot, fills = user_fills_from_message(_user_fill_message(snapshot=True))

    assert wallet == WALLET
    assert is_snapshot is True
    assert fills[0]["dir"] == "Open Long"


def test_user_fills_live_scan_stores_fresh_fill_and_delta(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'userfills.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))

    fake_ws = FakeWs([_user_fill_message(snapshot=False)])

    async def fake_connect(_url):
        return fake_ws

    # `websockets.connect` returns an async context manager, so expose one here too.
    def websocket_connect(_url):
        return fake_ws

    result = asyncio.run(
        scan_user_fills_ws(
            settings,
            wallets=[WALLET, "0x" + "d" * 40],
            duration_seconds=1,
            max_users=10,
            network_read=True,
            websocket_connect=websocket_connect,
        )
    )

    assert len(fake_ws.sent) == 2
    assert result.fills_seen == 1
    assert "_hypersmart_ws_received_at_ms" in result.wallet_fills[WALLET][0]
    with session_factory() as session:
        store_user_fills_live_result(session, result)
        session.commit()

        assert session.query(Fill).count() == 1
        delta = session.query(PositionDeltaModel).one()
        assert delta.action == "OPEN"
        assert delta.delta_type == "open_long"
        assert delta.source == "hyperliquid_ws:userFills"
        assert not any(str(key).startswith("_hypersmart_") for key in (delta.raw_json or {}))


def test_user_fills_live_scan_ignores_stale_updates_even_when_snapshot_flag_missing(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'userfills_stale.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))

    fake_ws = FakeWs([_user_fill_message(snapshot=False, fill_time_ms=now_ms() - 600_000, fill_hash="0xstale")])

    def websocket_connect(_url):
        return fake_ws

    result = asyncio.run(
        scan_user_fills_ws(
            settings,
            wallets=[WALLET],
            duration_seconds=1,
            max_users=10,
            network_read=True,
            websocket_connect=websocket_connect,
        )
    )

    assert result.fills_seen == 1
    with session_factory() as session:
        store_user_fills_live_result(session, result, max_live_fill_age_ms=120_000)
        session.commit()

        assert result.stale_fills_ignored == 1
        assert session.query(Fill).count() == 0
        assert session.query(PositionDeltaModel).count() == 0
