from __future__ import annotations

from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address


class WatchlistManager:
    def __init__(self, max_wallets: int = 10) -> None:
        self.max_wallets = max_wallets
        self.wallets: list[str] = []

    def add(self, address: str) -> bool:
        wallet = normalize_wallet_address(address)
        if wallet in self.wallets:
            return False
        if len(self.wallets) >= self.max_wallets:
            raise ValueError("watchlist limit reached")
        self.wallets.append(wallet)
        return True
