from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MarketWebSocketConfig:
    url: str = "wss://api.hyperliquid.xyz/ws"
    subscribe_user_streams: bool = False


class MarketWebSocketClient:
    """Placeholder for read-only market WebSocket subscriptions.

    User-specific streams are intentionally disabled in the MVP until wallets are shortlisted.
    """

    def __init__(self, config: MarketWebSocketConfig) -> None:
        self.config = config

    def assert_safe(self) -> None:
        if self.config.subscribe_user_streams:
            raise RuntimeError("User WebSocket streams are disabled until shortlist mode is built")
