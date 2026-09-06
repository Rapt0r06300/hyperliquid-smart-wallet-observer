from hl_observer.cli import app
from hl_observer.hyperliquid.ws_client import MarketWebSocketClient, MarketWebSocketConfig


if __name__ == "__main__":
    MarketWebSocketClient(MarketWebSocketConfig()).assert_safe()
    app()
