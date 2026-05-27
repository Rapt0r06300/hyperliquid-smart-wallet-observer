from hyper_smart_observer.hyperliquid_client.models import Wallet
from hyper_smart_observer.wallet_discovery.discovery_engine import WalletDiscoveryEngine


def test_wallet_discovery_deduplicates():
    wallet = "0x" + "a" * 40
    engine = WalletDiscoveryEngine()

    candidates = engine.from_wallets([wallet, wallet.upper()], source="manual")

    assert len(candidates) == 1
    assert candidates[0].wallet_address == wallet
