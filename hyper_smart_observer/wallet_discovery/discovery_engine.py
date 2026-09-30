from __future__ import annotations

from hyper_smart_observer.explorer_observer.explorer_discovery import wallets_from_explorer_events
from hyper_smart_observer.explorer_observer.explorer_models import ExplorerEvent
from hyper_smart_observer.wallet_discovery.candidate_sources import WalletCandidate, candidate_from_wallet


class WalletDiscoveryEngine:
    def dedupe(self, candidates: list[WalletCandidate]) -> list[WalletCandidate]:
        by_wallet: dict[str, WalletCandidate] = {}
        for candidate in candidates:
            existing = by_wallet.get(candidate.wallet_address)
            if existing is None or candidate.candidate_score > existing.candidate_score:
                by_wallet[candidate.wallet_address] = candidate
        return list(by_wallet.values())

    def from_wallets(self, wallets: list[str], *, source: str) -> list[WalletCandidate]:
        return [
            candidate
            for wallet in wallets
            if (candidate := candidate_from_wallet(wallet, source=source)) is not None
        ]

    def from_explorer_events(self, events: list[ExplorerEvent]) -> list[WalletCandidate]:
        return self.from_wallets(wallets_from_explorer_events(events), source="explorer_observer")
