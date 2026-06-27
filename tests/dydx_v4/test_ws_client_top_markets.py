from __future__ import annotations

from hyper_smart_observer.dydx_v4.ws_client import DEFAULT_TOP_TRADE_MARKETS, DydxIndexerWsClient


def test_subscribe_top_trade_markets_registers_read_only_trade_subscriptions(monkeypatch) -> None:
    client = DydxIndexerWsClient("wss://example.invalid")
    sent: list[str] = []

    def fake_send_subscription(key: str) -> None:
        sent.append(key)

    monkeypatch.setattr(client, "_send_subscription", fake_send_subscription)

    selected = client.subscribe_top_trade_markets(limit=5)

    assert selected == DEFAULT_TOP_TRADE_MARKETS[:5]
    assert sent == [f"v4_trades:{market}" for market in DEFAULT_TOP_TRADE_MARKETS[:5]]
    assert all(payload["channel"] == "v4_trades" for payload in client._subscriptions.values())
    assert all(payload["type"] == "subscribe" for payload in client._subscriptions.values())
