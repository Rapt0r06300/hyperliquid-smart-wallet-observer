from __future__ import annotations

from hyper_smart_observer.data_sources.local_cache_provider import LocalCacheProvider
from hyper_smart_observer.data_sources.official_info_provider import OfficialInfoProvider
from hyper_smart_observer.data_sources.official_ws_provider import OfficialWsProvider
from hyper_smart_observer.data_sources.provider_registry import default_provider_specs
from hyper_smart_observer.local_index.wallet_index import fake_wallet


class FakeInfoClient:
    def get_all_mids(self):
        return {"BTC": "50000"}

    def get_clearinghouse_state(self, address):
        return {"user": address, "assetPositions": []}

    def get_user_fills_by_time(self, address, start_time_ms, end_time_ms=None):
        return [{"user": address, "time": start_time_ms, "coin": "BTC"}]

    def get_user_fills(self, address, aggregate_by_time=False):
        return []

    def get_open_orders(self, address):
        return []

    def get_frontend_open_orders(self, address):
        return []


def test_provider_registry_has_safe_local_defaults_and_disabled_network() -> None:
    providers = {provider.provider_name: provider for provider in default_provider_specs()}

    assert providers["ManualImportProvider"].enabled_by_default is True
    assert providers["ManualImportProvider"].requires_network is False
    assert providers["LocalCacheProvider"].enabled_by_default is True
    assert providers["OfficialInfoProvider"].requires_network is True
    assert providers["OfficialInfoProvider"].enabled_by_default is False
    assert providers["OfficialWsProvider"].requires_network is True
    assert providers["OfficialWsProvider"].enabled_by_default is False
    assert all(provider.safe_by_default for provider in providers.values())


def test_local_cache_provider_scans_without_network() -> None:
    provider = LocalCacheProvider()
    for index in range(10):
        assert provider.upsert_wallet(fake_wallet(index + 1))

    summary = provider.scan_wallets(limit=5)

    assert summary.wallets_scanned == 5
    assert summary.network_used is False


def test_official_info_provider_requires_network_read_and_is_fake_client_testable() -> None:
    provider = OfficialInfoProvider(FakeInfoClient(), network_read=False)
    assert provider.health().message == "NETWORK_READ_DISABLED"

    enabled = OfficialInfoProvider(FakeInfoClient(), network_read=True)
    assert enabled.fetch_all_mids_once() == {"BTC": "50000"}
    snapshot = enabled.fetch_wallet_snapshot("0x" + "1" * 40, start_time_ms=123)
    assert snapshot["clearinghouseState"]["assetPositions"] == []
    assert snapshot["userFillsByTime"][0]["time"] == 123


def test_official_ws_provider_limits_users_and_requires_duration() -> None:
    provider = OfficialWsProvider(network_read=True)
    wallets = ["0x" + f"{i:040x}" for i in range(1, 11)]
    assert len(provider.validate_watchlist(wallets, duration_seconds=60)) == 10

    try:
        provider.validate_watchlist(wallets, duration_seconds=None)
    except ValueError as exc:
        assert str(exc) == "WEBSOCKET_DURATION_REQUIRED"
    else:
        raise AssertionError("duration guard did not fire")

    try:
        provider.validate_watchlist(wallets + ["0x" + "f" * 40], duration_seconds=60)
    except ValueError as exc:
        assert str(exc) == "WEBSOCKET_LIMIT_GUARD"
    else:
        raise AssertionError("user limit guard did not fire")
