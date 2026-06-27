from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.local_index.query_engine import LocalScanSummary, scan_wallet_index
from hyper_smart_observer.local_index.wallet_index import IndexedWallet, WalletLocalIndex


@dataclass(slots=True)
class LocalCacheProvider:
    name: str = "LocalCacheProvider"
    enabled_by_default: bool = True
    requires_network: bool = False
    requires_api_key: bool = False
    index: WalletLocalIndex = field(default_factory=WalletLocalIndex)

    def upsert_wallet(self, wallet: IndexedWallet) -> bool:
        return self.index.upsert(wallet)

    def scan_wallets(self, *, limit: int = 2_000) -> LocalScanSummary:
        return scan_wallet_index(self.index, limit=limit)
