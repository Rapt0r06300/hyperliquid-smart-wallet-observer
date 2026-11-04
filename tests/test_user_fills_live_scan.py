import asyncio
import json

import pytest

import hl_observer.wallets.user_fills_live as user_fills_live_module
from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import Fill, PositionDeltaModel, SourceHealth
from hl_observer.utils.time import now_ms
from hl_observer.wallets.user_fills_live import (
    UserFillsLiveResult,
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
                        # Hyperliquid's economic side is authoritative; the runtime
                        # must not infer it from the display-only ``dir`` label.
                        "side": "B",
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


def _subscription_ack(wallet: str = WALLET) -> str:
    return json.dumps({
        "channel": "subscriptionResponse",
        "data": {
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": wallet},
        },
    })


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


def test_user_fills_parser_recognizes_only_matching_subscription_ack():
    from hl_observer.wallets.user_fills_live import user_fills_subscription_ack

    assert user_fills_subscription_ack(_subscription_ack()) == WALLET
    assert user_fills_subscription_ack(_subscription_ack("0x" + "d" * 40)) == "0x" + "d" * 40
    assert user_fills_subscription_ack({"channel": "notification", "data": {}}) is None


@pytest.mark.parametrize("snapshot_value", [None, "false", 0, 1])
def test_user_fills_parser_does_not_coerce_unknown_snapshot_markers(snapshot_value):
    payload = json.loads(_user_fill_message(snapshot=False))
    if snapshot_value is None:
        payload["data"].pop("isSnapshot")
    else:
        payload["data"]["isSnapshot"] = snapshot_value

    wallet, is_snapshot, fills = user_fills_from_message(payload)

    assert wallet == WALLET
    assert is_snapshot is (snapshot_value if type(snapshot_value) is bool else None)
    assert len(fills) == 1


def test_user_fills_live_scan_stores_fresh_fill_and_delta(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'userfills.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))

    fake_ws = FakeWs([_subscription_ack(), _user_fill_message(snapshot=False)])

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
    assert result.subscription_acks_seen == 1
    assert "_hypersmart_ws_received_at_ms" in result.wallet_fills[WALLET][0]
    with session_factory() as session:
        store_user_fills_live_result(session, result)
        session.commit()

        assert session.query(Fill).count() == 1
        fill = session.query(Fill).one()
        assert fill.raw_json["observer_provenance"]["is_snapshot"] is False
        assert fill.raw_json["observer_provenance"]["ack_received_at_ms"] > 0
        assert fill.raw_json["observer_provenance"]["native_identity"]["hash"] == "0xfill"
        delta = session.query(PositionDeltaModel).one()
        assert delta.action == "OPEN"
        assert delta.delta_type == "open_long"
        assert delta.source == "hyperliquid_ws:userFills"
        assert not any(str(key).startswith("_hypersmart_") for key in (delta.raw_json or {}))


def test_user_fills_live_scan_quarantines_fill_before_subscription_ack():
    settings = load_settings()
    fake_ws = FakeWs([_user_fill_message(snapshot=False, fill_hash="0xbefore-ack")])

    result = asyncio.run(
        scan_user_fills_ws(
            settings,
            wallets=[WALLET],
            duration_seconds=1,
            network_read=True,
            websocket_connect=lambda _url: fake_ws,
        )
    )

    assert result.fills_seen == 0
    assert result.unacked_fills_ignored == 1
    assert result.wallet_fills == {}
    assert any("ACK" in warning for warning in result.warnings)


def test_user_fills_live_scan_ignores_stale_updates_even_when_snapshot_flag_missing(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'userfills_stale.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))

    fake_ws = FakeWs([
        _subscription_ack(),
        _user_fill_message(snapshot=False, fill_time_ms=now_ms() - 600_000, fill_hash="0xstale"),
    ])

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


def test_user_fills_live_scan_quarantines_unknown_snapshot_classification():
    settings = load_settings()
    fake_payload = json.loads(_user_fill_message(snapshot=False))
    fake_payload["data"]["isSnapshot"] = "false"

    class OneMessageWs(FakeWs):
        pass

    def websocket_connect(_url):
        return OneMessageWs([_subscription_ack(), json.dumps(fake_payload)])

    result = asyncio.run(
        scan_user_fills_ws(
            settings,
            wallets=[WALLET],
            duration_seconds=1,
            network_read=True,
            websocket_connect=websocket_connect,
        )
    )

    assert result.fills_seen == 0
    assert result.unclassified_fills_ignored == 1
    assert result.wallet_fills == {}


@pytest.mark.parametrize("value", [True, 1.5, "1000.5", 0, -1])
def test_store_user_fills_rejects_non_exact_causal_timestamps(tmp_path, value):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'invalid_timestamp.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))
    fill = {
        "coin": "BTC",
        "px": "100",
        "sz": "1",
        "time": 1000,
        "hash": "0xinvalid-ts",
        "tid": 99,
        "_hypersmart_ws_received_at_ms": value,
    }
    result = UserFillsLiveResult(
        wallets=[WALLET],
        duration_seconds=1,
        network_read=True,
        fills_seen=1,
        stopped_reason="duration_elapsed",
        wallet_fills={WALLET: [fill]},
    )

    with session_factory() as session:
        store_user_fills_live_result(session, result)
        session.commit()
        assert result.fills_stored == 0
        assert session.query(Fill).count() == 0


@pytest.mark.parametrize("receive_offset_ms", [None, -1_000])
def test_store_quarantines_fill_without_causal_receive_time(tmp_path, receive_offset_ms):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'userfills_missing_receive.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))
    source_time_ms = now_ms()
    fill = {
        "coin": "BTC",
        "dir": "Open Long",
        "px": "100",
        "sz": "1",
        "fee": "0.01",
        "time": source_time_ms if receive_offset_ms is None else source_time_ms + 1_000,
        "hash": "0xmissing-receive" if receive_offset_ms is None else "0ximpossible-chronology",
        "tid": 99,
        "oid": 100,
        "startPosition": "0",
        "_hypersmart_source": "hyperliquid_ws:userFills",
    }
    if receive_offset_ms is not None:
        fill["_hypersmart_ws_received_at_ms"] = source_time_ms + receive_offset_ms
    result = UserFillsLiveResult(
        wallets=[WALLET],
        duration_seconds=1,
        network_read=True,
        fills_seen=1,
        stopped_reason="duration_elapsed",
        wallet_fills={
            WALLET: [fill]
        },
    )

    with session_factory() as session:
        store_user_fills_live_result(session, result)
        session.commit()

        assert result.fills_stored == 0
        assert result.deltas_stored == 0
        assert session.query(Fill).count() == 0
        assert session.query(PositionDeltaModel).count() == 0
    assert any("timestamp" in warning for warning in result.warnings)


def test_store_fill_and_delta_are_atomic_when_delta_build_fails(tmp_path, monkeypatch):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'atomic_delta.sqlite3'}"
    init_db(settings.database_url)
    session_factory = create_session_factory(create_sqlite_engine(settings.database_url))
    fill = {
        "coin": "BTC", "px": "100", "sz": "1", "side": "B", "dir": "Open Long",
        "time": 1_000, "hash": "0xatomic", "tid": 1,
        "_hypersmart_ws_received_at_ms": 1_010,
    }
    result = UserFillsLiveResult(
        wallets=[WALLET], duration_seconds=1, network_read=True,
        fills_seen=1, stopped_reason="duration_elapsed", wallet_fills={WALLET: [fill]},
    )

    def fail_delta(*_args, **_kwargs):
        raise ValueError("delta unavailable")

    monkeypatch.setattr(user_fills_live_module, "build_position_delta_from_fill", fail_delta)
    with session_factory() as session:
        store_user_fills_live_result(session, result)
        session.commit()
        assert result.fills_stored == 0
        assert result.deltas_stored == 0
        assert result.fills_quarantined == 1
        assert session.query(Fill).count() == 0
        assert session.query(PositionDeltaModel).count() == 0
        health = session.query(SourceHealth).one()
        assert health.is_consistent is False
        assert health.freshness_status == "CONTRADICTORY"
        assert health.last_success_at_ms is None
