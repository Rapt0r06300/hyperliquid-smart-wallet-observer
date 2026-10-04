from hl_observer.collection.bitget_market_data import BitgetPublicClient
from hl_observer.collection.bybit_market_data import BybitPublicClient
from hl_observer.collection.gate_market_data import GatePublicClient
from hl_observer.collection.market_capture_tiers import CaptureTier, capture_profile
from hl_observer.collection.native_venue_coordinator import NativeVenueCoordinator
from hl_observer.collection.okx_market_data import OkxPublicClient


def test_clients_build_tier_specific_public_subscriptions() -> None:
    bybit = BybitPublicClient()
    bybit.set_capture_profile(CaptureTier.C)
    assert bybit.subscription_args(["BTCUSDT"]) == [
        "orderbook.1.BTCUSDT",
        "publicTrade.BTCUSDT",
    ]

    okx = OkxPublicClient()
    okx.set_capture_profile(CaptureTier.A)
    assert {row["channel"] for row in okx.subscription_args(["BTC-USDT-SWAP"])} >= {
        "books", "bbo-tbt", "trades", "funding-rate", "open-interest"
    }

    bitget = BitgetPublicClient()
    bitget.set_capture_profile(CaptureTier.B)
    assert {row["channel"] for row in bitget.subscription_args(["BTCUSDT"])} == {
        "books15", "books1", "ticker", "trade"
    }

    gate = GatePublicClient()
    gate.set_capture_profile(CaptureTier.C)
    assert {row["channel"] for row in gate.subscription_args(["BTC_USDT"])} == {
        "futures.book_ticker", "futures.trades"
    }


def test_coordinator_exposes_explicit_profile_without_changing_default() -> None:
    coordinator = NativeVenueCoordinator(
        capture_tiers={"bybit": {"BTCUSDT": "A"}},
        ccxt_snapshot_path=None,
    )
    assert coordinator.capture_profile_for("bybit", "BTCUSDT").tier is CaptureTier.A
    assert coordinator.capture_profile_for("bybit", "ETHUSDT").tier is CaptureTier.B


def test_mixed_symbol_tiers_do_not_force_deep_book_on_every_symbol() -> None:
    client = BybitPublicClient()
    client.set_capture_profiles({"BTCUSDT": CaptureTier.A, "ETHUSDT": CaptureTier.C})
    topics = set(client.subscription_args(["BTCUSDT", "ETHUSDT"]))
    assert "orderbook.1000.BTCUSDT" in topics
    assert "orderbook.1.ETHUSDT" in topics
    assert "orderbook.1000.ETHUSDT" not in topics


class _ClockClient:
    def __init__(self, venue: str) -> None:
        self.venue = venue

    def measure_clock_sync(self):
        return {"venue": self.venue, "offset_ms": 1.0, "rtt_ms": 2.0}


def test_clock_sync_covers_every_native_venue() -> None:
    coordinator = NativeVenueCoordinator(
        bybit_client=_ClockClient("bybit"),
        okx_client=_ClockClient("okx"),
        gate_client=_ClockClient("gate"),
        bitget_client=_ClockClient("bitget"),
        ccxt_snapshot_path=None,
    )
    assert set(coordinator.refresh_clock_sync()) == {"bybit", "okx", "gate", "bitget"}


def test_all_supported_market_venues_have_deterministic_abc_profiles() -> None:
    venues = {"binance", "hyperliquid", "deribit", "kraken", "coinbase", "htx"}
    for venue in venues:
        profiles = [capture_profile(venue, tier) for tier in CaptureTier]
        assert [profile.tier for profile in profiles] == list(CaptureTier)
        assert profiles[0].depth >= profiles[1].depth >= profiles[2].depth
        assert any("trade" in channel.lower() for channel in profiles[0].channels)
