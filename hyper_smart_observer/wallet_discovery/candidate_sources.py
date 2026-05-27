from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from hyper_smart_observer.hyperliquid_client.validation import is_valid_wallet_address


class WalletCandidateStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    ENRICHED = "ENRICHED"
    WATCHLIST_CANDIDATE = "WATCHLIST_CANDIDATE"
    WATCHLISTED = "WATCHLISTED"
    SHORTLISTED_FOR_WS = "SHORTLISTED_FOR_WS"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True)
class WalletCandidate:
    wallet_address: str
    source: str
    first_seen: datetime
    last_seen: datetime
    observed_trades: int = 0
    observed_notional: float | None = None
    observed_closed_pnl: float | None = None
    candidate_reason: str = "observed_public_activity"
    candidate_score: float = 0.0
    status: WalletCandidateStatus = WalletCandidateStatus.DISCOVERED
    warnings: list[str] = field(default_factory=list)


def candidate_from_wallet(address: str, *, source: str, reason: str = "manual_or_local_source") -> WalletCandidate | None:
    if not is_valid_wallet_address(address):
        return None
    now = datetime.now(UTC)
    return WalletCandidate(
        wallet_address=address.lower(),
        source=source,
        first_seen=now,
        last_seen=now,
        candidate_reason=reason,
        candidate_score=10.0,
    )
