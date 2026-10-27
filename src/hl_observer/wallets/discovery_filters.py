from __future__ import annotations

from hl_observer.wallets.discovery_scoring import WalletDiscoveryDecision
from hl_observer.wallets.discovery_sources import WalletDiscoveryCandidate, is_valid_portfolio_identity
from hl_observer.wallets.leaderboard_validation import is_truncated_wallet_display


def dedupe_candidates(
    candidates: list[WalletDiscoveryCandidate],
) -> tuple[list[WalletDiscoveryCandidate], dict[str, WalletDiscoveryDecision]]:
    seen: set[str] = set()
    rejected: dict[str, WalletDiscoveryDecision] = {}
    unique: list[WalletDiscoveryCandidate] = []
    for candidate in candidates:
        if not candidate.address:
            rejected["<missing>"] = WalletDiscoveryDecision.REJECT_NO_ADDRESS
            continue
        if is_truncated_wallet_display(candidate.address) or "..." in candidate.address:
            rejected[candidate.address] = WalletDiscoveryDecision.REJECT_TRUNCATED_ADDRESS
            continue
        identity = candidate.portfolio_identity
        if not is_valid_portfolio_identity(candidate):
            rejected[identity] = WalletDiscoveryDecision.REJECT_INVALID_ADDRESS
            continue
        if identity in seen:
            rejected[identity] = WalletDiscoveryDecision.REJECT_DUPLICATE
            continue
        seen.add(identity)
        unique.append(candidate)
    return unique, rejected
