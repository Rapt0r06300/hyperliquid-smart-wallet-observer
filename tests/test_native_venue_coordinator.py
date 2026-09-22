from __future__ import annotations

from hl_observer.collection.coin_universe import clear, coins
from hl_observer.collection.native_venue_coordinator import NativeVenueCoordinator


class _BybitDiscovery:
    def discover_usdt_perpetuals(self):
        return [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"), ("SOL", "SOLUSDT")]


class _OkxDiscovery:
    def discover_usdt_perpetuals(self):
        return [("BTC", "BTC-USDT-SWAP"), ("ETH", "ETH-USDT-SWAP"), ("XRP", "XRP-USDT-SWAP")]


class _EmptyDiscovery:
    def discover_usdt_perpetuals(self):
        return []


def test_discovery_builds_registry_and_feeds_coin_universe() -> None:
    clear()
    coordinator = NativeVenueCoordinator(
        bybit_client=_BybitDiscovery(),
        okx_client=_OkxDiscovery(),
        gate_client=_EmptyDiscovery(),
        bitget_client=_EmptyDiscovery(),
        stale_after_ms=2_000,
    )
    registry = coordinator.discover(now_s=100.0)

    assert registry["BTC"] == {"bybit": "BTCUSDT", "okx": "BTC-USDT-SWAP"}
    assert registry["ETH"] == {"bybit": "ETHUSDT", "okx": "ETH-USDT-SWAP"}
    assert registry["SOL"] == {"bybit": "SOLUSDT"}
    assert registry["XRP"] == {"okx": "XRP-USDT-SWAP"}
    assert set(coins(limit=10, now_s=100.0)) == {"BTC", "ETH", "SOL", "XRP"}


def test_routes_bybit_okx_and_existing_bbo_into_one_store() -> None:
    coordinator = NativeVenueCoordinator(stale_after_ms=2_000)

    coordinator.ingest_external_bbo(
        venue="hyperliquid",
        coin="BTC",
        exchange_symbol="BTC",
        bid=100.0,
        ask=100.1,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_010,
        now_ms=1_020,
    )
    coordinator.ingest_external_bbo(
        venue="binance",
        coin="BTC",
        exchange_symbol="BTCUSDT",
        bid=100.2,
        ask=100.3,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_010,
        now_ms=1_020,
    )

    coordinator.ingest_bybit(
        {
            "type": "snapshot",
            "ts": 1_000,
            "data": {
                "s": "BTCUSDT",
                "b": [["100.4", "2"]],
                "a": [["100.5", "2"]],
                "u": 1,
                "seq": 1,
            },
        },
        receive_ts_ms=1_010,
        now_ms=1_020,
    )
    coordinator.ingest_okx(
        {
            "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "ts": "1000",
                    "seqId": 1,
                    "prevSeqId": -1,
                    "bids": [["100.6", "2", "0", "1"]],
                    "asks": [["100.7", "2", "0", "1"]],
                }
            ],
        },
        receive_ts_ms=1_010,
        now_ms=1_020,
    )

    assert coordinator.candidate_coins(now_ms=1_100, min_venues=2) == ["BTC"]
    assert set(coordinator.store.venue_pairs("BTC", now_ms=1_100)) == {
        ("binance", "bybit"),
        ("binance", "hyperliquid"),
        ("binance", "okx"),
        ("bybit", "hyperliquid"),
        ("bybit", "okx"),
        ("hyperliquid", "okx"),
    }
    assert len(coordinator.lead_lag_rows("BTC", now_ms=1_100)) == 4
    discrepancies = coordinator.cross_venue_rows("BTC", now_ms=1_100)
    assert len(discrepancies) == 1
    assert discrepancies[0].coin == "BTC"
    assert discrepancies[0].source_achat == "hyperliquid"
    assert discrepancies[0].source_vente == "okx"


def test_stale_venue_is_excluded_fail_closed() -> None:
    coordinator = NativeVenueCoordinator(stale_after_ms=100)
    coordinator.ingest_external_bbo(
        venue="bybit",
        coin="ETH",
        exchange_symbol="ETHUSDT",
        bid=10.0,
        ask=10.1,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_000,
        now_ms=1_000,
    )
    coordinator.ingest_external_bbo(
        venue="okx",
        coin="ETH",
        exchange_symbol="ETH-USDT-SWAP",
        bid=10.2,
        ask=10.3,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_000,
        now_ms=1_000,
    )

    assert coordinator.candidate_coins(now_ms=1_500, min_venues=2) == []
    assert coordinator.cross_venue_rows("ETH", now_ms=1_500) == []


def test_cross_venue_rejects_unsynchronized_executable_legs() -> None:
    coordinator = NativeVenueCoordinator(stale_after_ms=2_000)
    coordinator.ingest_external_bbo(
        venue="hyperliquid",
        coin="BTC",
        exchange_symbol="BTC",
        bid=99.9,
        ask=100.0,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_000,
        now_ms=1_400,
    )
    coordinator.ingest_external_bbo(
        venue="binance",
        coin="BTC",
        exchange_symbol="BTCUSDT",
        bid=101.0,
        ask=101.1,
        exchange_ts_ms=1_390,
        receive_ts_ms=1_400,
        now_ms=1_400,
    )

    assert coordinator.cross_venue_rows(
        "BTC",
        now_ms=1_400,
        max_receive_skew_ms=250,
    ) == []


def test_cross_venue_can_require_real_l2() -> None:
    coordinator = NativeVenueCoordinator(stale_after_ms=2_000)
    coordinator.ingest_external_bbo(
        venue="hyperliquid",
        coin="ETH",
        exchange_symbol="ETH",
        bid=99.9,
        ask=100.0,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_010,
        now_ms=1_020,
    )
    coordinator.ingest_external_bbo(
        venue="binance",
        coin="ETH",
        exchange_symbol="ETHUSDT",
        bid=101.0,
        ask=101.1,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_010,
        now_ms=1_020,
    )

    assert coordinator.cross_venue_rows(
        "ETH",
        now_ms=1_020,
        require_l2=True,
    ) == []


def test_symbol_shards_are_disjoint_and_preserve_ranked_coverage() -> None:
    left = NativeVenueCoordinator(
        bybit_client=_BybitDiscovery(),
        okx_client=_EmptyDiscovery(),
        gate_client=_EmptyDiscovery(),
        bitget_client=_EmptyDiscovery(),
        max_symbols_per_venue=3,
        symbol_shard_count=2,
        symbol_shard_index=0,
        ccxt_snapshot_path=None,
    )
    right = NativeVenueCoordinator(
        bybit_client=_BybitDiscovery(),
        okx_client=_EmptyDiscovery(),
        gate_client=_EmptyDiscovery(),
        bitget_client=_EmptyDiscovery(),
        max_symbols_per_venue=3,
        symbol_shard_count=2,
        symbol_shard_index=1,
        ccxt_snapshot_path=None,
    )
    left.discover(now_s=100.0)
    right.discover(now_s=100.0)

    left_symbols = left.symbols_for("bybit")
    right_symbols = right.symbols_for("bybit")
    assert set(left_symbols).isdisjoint(right_symbols)
    assert set(left_symbols) | set(right_symbols) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert len(left_symbols) == 2
    assert len(right_symbols) == 1


def test_invalid_symbol_shard_index_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        NativeVenueCoordinator(
            symbol_shard_count=2,
            symbol_shard_index=2,
            ccxt_snapshot_path=None,
        )


class _MutableBybitDiscovery:
    def __init__(self) -> None:
        self.rows = [("BTC", "BTCUSDT")]
        self.message_calls: list[tuple[str, ...]] = []

    def discover_usdt_perpetuals(self):
        return list(self.rows)

    async def messages(self, symbols):
        self.message_calls.append(tuple(symbols))
        while True:
            await asyncio.sleep(3600)
            yield {}


def test_discovery_refresh_detects_new_listing_without_restart() -> None:
    async def scenario() -> None:
        client = _MutableBybitDiscovery()
        coordinator = NativeVenueCoordinator(
            bybit_client=client,
            okx_client=_EmptyDiscovery(),
            gate_client=_EmptyDiscovery(),
            bitget_client=_EmptyDiscovery(),
        )
        coordinator.discover(now_s=100.0)
        assert "ETH" not in coordinator.registry

        client.rows.append(("ETH", "ETHUSDT"))
        coordinator.discovery_refresh_interval_s = 0.01
        task = asyncio.create_task(coordinator.run_discovery_refresh())
        try:
            await asyncio.sleep(0.04)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        assert coordinator.registry["ETH"]["bybit"] == "ETHUSDT"
        health = coordinator.health(now_ms=100_000)
        assert health["discovery_refreshes"] >= 1
        assert health["universe_changes"] >= 1

    import asyncio
    asyncio.run(scenario())


def test_venue_session_recycles_and_re_reads_symbol_universe() -> None:
    async def scenario() -> None:
        client = _MutableBybitDiscovery()
        coordinator = NativeVenueCoordinator(
            bybit_client=client,
            okx_client=_EmptyDiscovery(),
            gate_client=_EmptyDiscovery(),
            bitget_client=_EmptyDiscovery(),
        )
        coordinator.discover(now_s=100.0)
        coordinator.venue_session_s = 0.01

        await coordinator.run_bybit()
        assert client.message_calls[-1] == ("BTCUSDT",)

        client.rows.append(("ETH", "ETHUSDT"))
        coordinator.discover(now_s=101.0)
        await coordinator.run_bybit()
        assert set(client.message_calls[-1]) == {"BTCUSDT", "ETHUSDT"}

    import asyncio
    asyncio.run(scenario())
