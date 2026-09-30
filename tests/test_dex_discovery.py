from __future__ import annotations

from types import SimpleNamespace

from hl_observer.markets.dex_discovery import (
    DexCandidate,
    DexDiscoveryRadar,
    GeckoTerminalProvider,
)
from hl_observer.markets.universal_registry import (
    AvailabilityStatus,
    DiscoveryEventType,
    UniversalMarketRegistry,
)

NOW_MS = 2_000_000_000_000


def _candidate(*, coin: str = "WIF", source: str = "geckoterminal") -> DexCandidate:
    return DexCandidate(
        coin=coin,
        source=source,
        chain="solana",
        venue="raydium",
        pair=f"{coin}/USDC",
        pool_id=f"solana_pool_{coin.lower()}",
        pool_url=f"https://www.geckoterminal.com/solana/pools/pool_{coin.lower()}",
        price_usd=2.5,
        liquidity_usd=250_000.0,
        volume_24h_usd=500_000.0,
        transactions_24h=1_200,
        pair_created_at_ms=NOW_MS - 3_600_000,
        observed_at_ms=NOW_MS,
    )


def test_geckoterminal_normalizes_and_filters_new_pools() -> None:
    payload = {
        "data": [
            {
                "type": "pool",
                "id": "solana_pool_wif",
                "attributes": {
                    "address": "pool_wif",
                    "name": "WIF / USDC",
                    "base_token_price_usd": "2.5",
                    "reserve_in_usd": "250000",
                    "volume_usd": {"h24": "500000"},
                    "transactions": {"h24": {"buys": 700, "sells": 500}},
                    "pool_created_at": "2033-05-18T02:33:20Z",
                },
                "relationships": {
                    "base_token": {"data": {"type": "token", "id": "solana_wif"}},
                    "quote_token": {"data": {"type": "token", "id": "solana_usdc"}},
                    "dex": {"data": {"type": "dex", "id": "raydium"}},
                },
            },
            {
                "type": "pool",
                "id": "solana_pool_dust",
                "attributes": {
                    "address": "pool_dust",
                    "name": "DUST / USDC",
                    "reserve_in_usd": "25",
                    "volume_usd": {"h24": "10"},
                    "pool_created_at": "2033-05-18T02:33:20Z",
                },
                "relationships": {
                    "base_token": {"data": {"type": "token", "id": "solana_dust"}},
                    "quote_token": {"data": {"type": "token", "id": "solana_usdc"}},
                    "dex": {"data": {"type": "dex", "id": "raydium"}},
                },
            },
        ],
        "included": [
            {"type": "token", "id": "solana_wif", "attributes": {"symbol": "WIF"}},
            {"type": "token", "id": "solana_dust", "attributes": {"symbol": "DUST"}},
            {"type": "token", "id": "solana_usdc", "attributes": {"symbol": "USDC"}},
            {"type": "dex", "id": "raydium", "attributes": {"name": "Raydium"}},
        ],
    }
    provider = GeckoTerminalProvider(
        networks=("solana",),
        fetch_json=lambda _url: payload,
        min_liquidity_usd=10_000,
        min_volume_24h_usd=20_000,
        max_pair_age_hours=24,
    )

    rows = provider.discover(now_ms=NOW_MS)

    assert rows == [_candidate()]


def test_dex_radar_isolates_a_broken_provider() -> None:
    class BrokenProvider:
        name = "broken"

        def discover(self, *, now_ms: int):
            raise RuntimeError("offline")

    class WorkingProvider:
        name = "geckoterminal"

        def discover(self, *, now_ms: int):
            return [_candidate()]

    result = DexDiscoveryRadar([BrokenProvider(), WorkingProvider()]).discover(now_ms=NOW_MS)

    assert result.candidates == (_candidate(),)
    assert result.successful_providers == ("geckoterminal",)
    assert result.errors_by_provider == {"broken": "offline"}


def test_dex_candidates_feed_registry_events_metrics_and_hot_queue() -> None:
    result = DexDiscoveryRadar([_StaticProvider([_candidate()])]).discover(now_ms=NOW_MS)
    registry = UniversalMarketRegistry(native_venues={"binance"})

    events = registry.ingest_dex(result, observed_at_ms=NOW_MS)

    instrument = registry.market("WIF").instruments_for_venue("raydium")[0]
    assert instrument.status is AvailabilityStatus.DISCOVERY_ONLY
    assert {event.event_type for event in events} == {
        DiscoveryEventType.NEW_MARKET,
        DiscoveryEventType.NEW_DEX_PAIR,
    }
    assert registry.market("WIF").liquidity == 250_000.0
    hot = registry.hot_candidates(now_ms=NOW_MS)[0]
    assert hot.source == "geckoterminal"
    assert hot.venues == ("raydium",)
    assert hot.expires_at_ms == NOW_MS + 72 * 3_600_000


def test_scoped_dex_failure_does_not_delist_cex_or_previous_dex_pair() -> None:
    registry = UniversalMarketRegistry(native_venues={"binance"})
    registry.apply_snapshot(
        [{"coin": "BTC", "venue": "binance", "symbol": "BTC/USDT", "market_type": "spot"}],
        observed_at_ms=1,
        source="ccxt",
    )
    registry.ingest_dex(
        DexDiscoveryRadar([_StaticProvider([_candidate()])]).discover(now_ms=2),
        observed_at_ms=2,
    )

    failed = DexDiscoveryRadar([_BrokenProvider()]).discover(now_ms=3)
    events = registry.ingest_dex(failed, observed_at_ms=3)

    assert events == []
    assert registry.market("BTC").instruments_for_venue("binance")[0].active is True
    assert registry.market("WIF").instruments_for_venue("raydium")[0].active is True


def test_spot_listing_and_enriched_hot_candidate_survive_dump_load(tmp_path) -> None:
    registry = UniversalMarketRegistry(native_venues={"binance"})
    events = registry.apply_snapshot(
        [{"coin": "ENA", "venue": "binance", "symbol": "ENA/USDT", "market_type": "spot"}],
        observed_at_ms=100,
        source="ccxt",
    )
    path = tmp_path / "registry.json"
    registry.dump(path)
    restored = UniversalMarketRegistry.load(path)

    assert DiscoveryEventType.NEW_SPOT in {event.event_type for event in events}
    hot = restored.hot_candidates(now_ms=101)[0]
    assert hot.source == "ccxt"
    assert hot.venues == ("binance",)


def test_ccxt_ingest_emits_listing_events_and_hot_candidate() -> None:
    registry = UniversalMarketRegistry(native_venues={"binance"})
    result = SimpleNamespace(
        markets=[
            SimpleNamespace(
                canonical_base="ENA",
                venue="binance",
                exchange_symbol="ENA/USDT:USDT",
                active=True,
                market_type="perp",
                quote="USDT",
                settle_currency="USDT",
                linear=True,
                inverse=False,
                contract_size=1.0,
                discovered_at="2033-05-18T03:33:20Z",
            )
        ]
    )

    events = registry.ingest_ccxt(result)

    assert {event.event_type for event in events} == {
        DiscoveryEventType.NEW_MARKET,
        DiscoveryEventType.NEW_PERP,
    }
    hot = registry.hot_candidates(now_ms=NOW_MS)[0]
    assert hot.source == "ccxt"
    assert hot.venues == ("binance",)


def test_recent_listing_gets_simple_candidate_priority_bonus() -> None:
    registry = UniversalMarketRegistry(native_venues={"binance"})
    registry.register("COLD", "binance", "COLD/USDT", native=True, market_type="spot")
    registry.apply_snapshot(
        [{"coin": "HOT", "venue": "binance", "symbol": "HOT/USDT", "market_type": "spot"}],
        observed_at_ms=100,
        source="ccxt",
    )

    scores = {candidate.coin: candidate.score for candidate in registry.candidates()}

    assert scores["HOT"] == scores["COLD"] + 10


class _StaticProvider:
    name = "geckoterminal"

    def __init__(self, candidates):
        self.candidates = candidates

    def discover(self, *, now_ms: int):
        return self.candidates


class _BrokenProvider:
    name = "geckoterminal"

    def discover(self, *, now_ms: int):
        raise RuntimeError("offline")
