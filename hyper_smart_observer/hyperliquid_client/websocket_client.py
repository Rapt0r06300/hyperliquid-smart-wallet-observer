from __future__ import annotations

from hyper_smart_observer.app.config import AppConfig


class HyperliquidWebSocketClient:
    """WebSocket scaffold; no automatic connection in Sprint 1.

    Future subscriptions must respect official limits and remain read-only
    unless the testnet-only guard explicitly allows mock-USDC testnet actions.
    Planned feeds: allMids, l2Book, trades, userFills, userEvents, orderUpdates.
    """

    def __init__(self, config: AppConfig):
        self.base_url = config.hyperliquid_ws_base_url
        self.subscriptions: set[str] = set()

    def subscribe(self, channel: str) -> None:
        self.subscriptions.add(channel)

    def unsubscribe(self, channel: str) -> None:
        self.subscriptions.discard(channel)
