from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.local_index.wallet_index import IndexedWallet, WalletLocalIndex


@dataclass(slots=True)
class LocalScanSummary:
    wallets_scanned: int
    top_wallets: list[IndexedWallet]
    rejected_count: int
    network_used: bool = False
    stopped_reason: str = "LOCAL_SCAN_COMPLETE"


def scan_wallet_index(index: WalletLocalIndex, *, limit: int = 2_000) -> LocalScanSummary:
    rows = index.scan(limit=limit)
    return LocalScanSummary(
        wallets_scanned=len(rows),
        top_wallets=rows[: min(10, len(rows))],
        rejected_count=len(index.rejected),
    )
