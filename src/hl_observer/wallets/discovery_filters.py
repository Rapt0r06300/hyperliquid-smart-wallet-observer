from __future__ import annotations

from hl_observer.wallets.discovery_scoring import WalletDiscoveryDecision
from hl_observer.wallets.discovery_sources import WalletDiscoveryCandidate, is_valid_discovery_address
from hl_observer.wallets.leaderboard_validation import is_truncated_wallet_display


def dedupe_candidates(
    candidates: list[WalletDiscoveryCandidate],
) -> tuple[list[WalletDiscoveryCandidate], dict[str, WalletDiscoveryDecision]]:
    seen: set[str] = set()
    by_address: dict[str, WalletDiscoveryCandidate] = {}
    rejected: dict[str, WalletDiscoveryDecision] = {}
    unique: list[WalletDiscoveryCandidate] = []
    for candidate in candidates:
        if not candidate.address:
            rejected["<missing>"] = WalletDiscoveryDecision.REJECT_NO_ADDRESS
            continue
        if is_truncated_wallet_display(candidate.address) or "..." in candidate.address:
            rejected[candidate.address] = WalletDiscoveryDecision.REJECT_TRUNCATED_ADDRESS
            continue
        normalized = candidate.address.lower()
        if not is_valid_discovery_address(candidate.address):
            rejected[candidate.address] = WalletDiscoveryDecision.REJECT_INVALID_ADDRESS
            continue
        if normalized in seen:
            existing = by_address[normalized]
            merged_activity = False
            if (
                candidate.source_name == "public_trades_ws"
                and candidate.activity_evidence_verified
                and not existing.activity_evidence_verified
            ):
                existing.activity_evidence_verified = True
                existing.activity_trade_count = candidate.activity_trade_count
                existing.activity_window_start_ms = candidate.activity_window_start_ms
                existing.activity_window_end_ms = candidate.activity_window_end_ms
                existing.last_trade_event_ms = candidate.last_trade_event_ms
                existing.raw_payload.setdefault("public_trade_activity", candidate.raw_payload)
                merged_activity = True
            if not merged_activity:
                rejected[candidate.address] = WalletDiscoveryDecision.REJECT_DUPLICATE
            continue
        seen.add(normalized)
        by_address[normalized] = candidate
        unique.append(candidate)
    return unique, rejected
