from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from hyper_smart_observer.data_sources.base_provider import ProviderHealth


class InfoClientProtocol(Protocol):
    def get_all_mids(self) -> dict[str, Any]: ...

    def get_clearinghouse_state(self, address: str) -> dict[str, Any]: ...

    def get_user_fills_by_time(self, address: str, start_time_ms: int, end_time_ms: int | None = None) -> list[dict[str, Any]]: ...

    def get_user_fills(self, address: str, aggregate_by_time: bool = False) -> list[dict[str, Any]]: ...

    def get_open_orders(self, address: str) -> list[dict[str, Any]]: ...

    def get_frontend_open_orders(self, address: str) -> list[dict[str, Any]]: ...


@dataclass(slots=True)
class OfficialInfoProvider:
    client: InfoClientProtocol
    network_read: bool = False
    name: str = "OfficialInfoProvider"
    enabled_by_default: bool = False
    requires_network: bool = True
    requires_api_key: bool = False

    def health(self) -> ProviderHealth:
        if not self.network_read:
            return ProviderHealth(self.name, False, "NETWORK_READ_DISABLED", True, False)
        return ProviderHealth(self.name, True, "READ_ONLY_INFO_ENABLED", True, True)

    def fetch_wallet_snapshot(self, address: str, *, start_time_ms: int, end_time_ms: int | None = None) -> dict[str, Any]:
        if not self.network_read:
            raise PermissionError("NETWORK_READ_DISABLED")
        return {
            "address": address,
            "clearinghouseState": self.client.get_clearinghouse_state(address),
            "userFillsByTime": self.client.get_user_fills_by_time(address, start_time_ms, end_time_ms),
            "userFills": self.client.get_user_fills(address, aggregate_by_time=False),
            "openOrders": self.client.get_open_orders(address),
            "frontendOpenOrders": self.client.get_frontend_open_orders(address),
        }

    def fetch_all_mids_once(self) -> dict[str, Any]:
        if not self.network_read:
            raise PermissionError("NETWORK_READ_DISABLED")
        return self.client.get_all_mids()
