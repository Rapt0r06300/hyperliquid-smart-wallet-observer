"""R14 (robustesse) — le scan read-only ne doit PAS crasher sur coupure reseau/DNS.
Il rend un etat vide honnete (NETWORK_UNREACHABLE / INSUFFICIENT_DATA). Paper/read-only."""

import asyncio

import hl_observer.markets.scanner as scanner
from hl_observer.config.settings import Settings
from hl_observer.markets.scanner import (
    MarketDiscoveryPlan,
    MarketScanPlan,
    run_discover_markets,
    run_scan_markets,
)


class _DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _settings():
    return Settings()


def test_discover_markets_degrades_on_dns_failure(monkeypatch):
    async def _boom(*a, **k):
        raise OSError("[Errno 11001] getaddrinfo failed")
    monkeypatch.setattr(scanner, "fetch_market_universe", _boom)
    res = asyncio.run(run_discover_markets(
        MarketDiscoveryPlan(dry_run=False, store=False), _settings(), client=_DummyClient()))
    assert res.coins_discovered == 0
    assert "NETWORK_UNREACHABLE" in res.notes
    assert "INSUFFICIENT_DATA" in res.notes


def test_scan_markets_degrades_on_dns_failure(monkeypatch):
    async def _boom(*a, **k):
        raise OSError("[Errno 11001] getaddrinfo failed")
    monkeypatch.setattr(scanner, "fetch_market_universe", _boom)
    res = asyncio.run(run_scan_markets(
        MarketScanPlan(all_coins=True, dry_run=False, store=False),
        _settings(), client=_DummyClient(), session_factory=object()))
    assert res.errors_count >= 1
    assert "NETWORK_UNREACHABLE" in res.notes
    assert res.metrics == []
