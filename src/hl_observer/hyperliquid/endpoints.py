from __future__ import annotations

from hl_observer.config.settings import ExecutionEnvironment, Settings

MAINNET_INFO_URL = "https://api.hyperliquid.xyz/info"
TESTNET_INFO_URL = "https://api.hyperliquid-testnet.xyz/info"
MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"
TESTNET_WS_URL = "wss://api.hyperliquid-testnet.xyz/ws"


def info_url_for_settings(settings: Settings) -> str:
    if settings.environment == ExecutionEnvironment.TESTNET:
        return settings.hyperliquid.testnet_info_base_url
    return settings.hyperliquid.info_base_url


def ws_url_for_settings(settings: Settings) -> str:
    if settings.environment == ExecutionEnvironment.TESTNET:
        return settings.hyperliquid.testnet_ws_base_url
    return settings.hyperliquid.ws_base_url
