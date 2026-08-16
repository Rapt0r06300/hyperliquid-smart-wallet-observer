from __future__ import annotations

import json

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.realtime_monitor.stream_models import StreamType
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription
from hyper_smart_observer.realtime_monitor.websocket_manager import WebSocketManager


class _Clock:
    def __init__(self, step: float = 0.05) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current

    def sleep(self, seconds: float) -> None:
        self.value += max(0.0, seconds)


class _FakeSocket:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = [json.dumps(row) for row in messages]
        self.sent: list[dict] = []
        self.closed = False
        self.timeout = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def recv(self) -> str:
        if self.messages:
            return self.messages.pop(0)
        raise TimeoutError("fake receive timeout")

    def close(self) -> None:
        self.closed = True


def _config(**overrides) -> AppConfig:
    values = {
        "enable_network_reads": True,
        "ws_monitor_enabled": True,
        "hyperliquid_ws_base_url": "wss://api.hyperliquid-testnet.xyz/ws",
    }
    values.update(overrides)
    return AppConfig(**values)


def _wallet(index: int) -> str:
    return "0x" + f"{index:040x}"


def test_ws_runtime_snapshot_duplicate_heartbeat_et_sorties_read_only() -> None:
    wallet = _wallet(1)
    fill = {
        "coin": "BTC",
        "px": "60000",
        "sz": "0.001",
        "side": "B",
        "time": 123,
        "startPosition": "0",
        "dir": "Open Long",
        "closedPnl": "0",
        "hash": "0xabc",
        "oid": 42,
        "tid": 99,
    }
    snapshot = {
        "channel": "userFills",
        "data": {"isSnapshot": True, "user": wallet, "fills": [fill]},
    }
    fake = _FakeSocket([snapshot, snapshot])
    clock = _Clock(step=0.05)
    manager = WebSocketManager(_config())

    report = manager.run_bounded(
        [Subscription(StreamType.USER_FILLS, user=wallet)],
        duration_seconds=1,
        connector=lambda *_args, **_kwargs: fake,
        clock=clock,
        sleeper=clock.sleep,
        heartbeat_seconds=0.10,
        receive_timeout_seconds=0.01,
        max_events=20,
    )

    assert report.read_only is True
    assert report.bounded_duration is True
    assert report.connected_sessions == 1
    assert report.events_routed == 1
    assert report.snapshot_messages == 1
    assert report.duplicate_messages == 1
    assert report.heartbeat_count >= 1
    assert report.fallback_to_rest_polling is False
    assert fake.closed is True
    methods = {row.get("method") for row in fake.sent}
    assert methods <= {"subscribe", "unsubscribe", "ping"}
    assert "subscribe" in methods
    assert "unsubscribe" in methods
    assert "ping" in methods
    encoded = json.dumps(fake.sent).casefold()
    assert '"method": "post"' not in encoded
    assert '"type": "action"' not in encoded
    assert "exchange" not in encoded


def test_ws_runtime_refuse_si_network_read_non_explicitement_active() -> None:
    called = False

    def connector(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("le connecteur ne doit jamais être appelé")

    manager = WebSocketManager(_config(enable_network_reads=False))
    report = manager.run_bounded(
        [Subscription(StreamType.ALL_MIDS)],
        duration_seconds=5,
        connector=connector,
    )

    assert called is False
    assert report.connected_sessions == 0
    assert report.fallback_to_rest_polling is True
    assert report.stopped_reason == "ws_plan_warning_fallback_rest_polling"


def test_ws_runtime_refuse_plus_de_dix_wallets_uniques() -> None:
    subscriptions = [
        Subscription(StreamType.USER_FILLS, user=_wallet(index + 1))
        for index in range(11)
    ]
    manager = WebSocketManager(_config(ws_max_user_subscriptions=10))
    report = manager.run_bounded(subscriptions, duration_seconds=5, connector=lambda *_a, **_k: None)

    assert report.connected_sessions == 0
    assert report.fallback_to_rest_polling is True
    assert any("too many unique user" in warning for warning in report.warnings)


def test_ws_runtime_refuse_toute_duree_non_bornee() -> None:
    manager = WebSocketManager(_config())
    report = manager.run_bounded(
        [Subscription(StreamType.ALL_MIDS)],
        duration_seconds=0,
        connector=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("pas de connexion")),
    )
    assert report.connected_sessions == 0
    assert report.fallback_to_rest_polling is True
    assert report.stopped_reason == "unbounded_duration_fallback_rest_polling"
