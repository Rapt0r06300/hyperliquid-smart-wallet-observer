from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.ws_client import DydxIndexerWsClient, WsStatus


class _FakeWs:
    def __init__(self, connected: bool) -> None:
        self.sock = SimpleNamespace(connected=connected)
        self.sent: list[str] = []

    def send(self, payload: str) -> None:
        self.sent.append(payload)


def test_subscription_is_queued_when_socket_is_not_connected() -> None:
    client = DydxIndexerWsClient("wss://example.invalid/v4/ws")
    fake = _FakeWs(connected=False)
    client._ws = fake
    client._status = WsStatus.CONNECTED

    client.subscribe_trades("BTC-USD")

    assert "v4_trades:BTC-USD" in client._subscriptions
    assert fake.sent == []
    assert client.status == WsStatus.CONNECTED


def test_subscription_sends_when_socket_is_connected() -> None:
    client = DydxIndexerWsClient("wss://example.invalid/v4/ws")
    fake = _FakeWs(connected=True)
    client._ws = fake
    client._status = WsStatus.CONNECTED

    client.subscribe_trades("ETH-USD")

    assert len(fake.sent) == 1
    assert '"channel": "v4_trades"' in fake.sent[0]
    assert '"id": "ETH-USD"' in fake.sent[0]
