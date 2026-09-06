import pytest

from hl_observer.hyperliquid.ws_client import MarketWebSocketClient, MarketWebSocketConfig


def test_market_websocket_client_accepts_read_only_default() -> None:
    client = MarketWebSocketClient(MarketWebSocketConfig())

    client.assert_safe()

    assert client.config.subscribe_user_streams is False


def test_market_websocket_client_rejects_user_streams() -> None:
    client = MarketWebSocketClient(MarketWebSocketConfig(subscribe_user_streams=True))

    with pytest.raises(RuntimeError, match="User WebSocket streams are disabled"):
        client.assert_safe()
