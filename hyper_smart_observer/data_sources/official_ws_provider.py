from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.data_sources.base_provider import ProviderHealth


@dataclass(slots=True)
class OfficialWsProvider:
    network_read: bool = False
    max_unique_users: int = 10
    name: str = "OfficialWsProvider"
    enabled_by_default: bool = False
    requires_network: bool = True
    requires_api_key: bool = False

    def health(self) -> ProviderHealth:
        if not self.network_read:
            return ProviderHealth(self.name, False, "NETWORK_READ_DISABLED", True, False)
        return ProviderHealth(self.name, True, "READ_ONLY_WS_ENABLED", True, True)

    def validate_watchlist(self, wallets: list[str], *, duration_seconds: int | None) -> list[str]:
        if duration_seconds is None or duration_seconds <= 0:
            raise ValueError("WEBSOCKET_DURATION_REQUIRED")
        unique = list(dict.fromkeys(wallet.lower() for wallet in wallets))
        if len(unique) > self.max_unique_users:
            raise ValueError("WEBSOCKET_LIMIT_GUARD")
        return unique
