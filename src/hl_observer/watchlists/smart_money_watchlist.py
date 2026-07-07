"""Smart-money watchlist builder with strict wallet validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


FULL_WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True, slots=True)
class WatchlistWallet:
    wallet: str
    score: float
    source: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SmartMoneyWatchlist:
    accepted: tuple[WatchlistWallet, ...]
    rejected: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def wallets(self) -> tuple[str, ...]:
        return tuple(item.wallet for item in self.accepted)


def build_smart_money_watchlist(
    rows: Iterable[dict[str, object]],
    *,
    max_wallets: int = 10,
    min_score: float = 0.0,
) -> SmartMoneyWatchlist:
    accepted: list[WatchlistWallet] = []
    rejected: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        raw = str(row.get("wallet") or row.get("address") or "").strip()
        score = float(row.get("score") or row.get("wallet_score") or 0.0)
        if "..." in raw:
            rejected.append({"wallet": raw, "reason": "TRUNCATED_ADDRESS_REJECTED"})
            continue
        if not FULL_WALLET_RE.match(raw):
            rejected.append({"wallet": raw, "reason": "INVALID_ADDRESS_REJECTED"})
            continue
        wallet = raw.lower()
        if wallet in seen:
            rejected.append({"wallet": wallet, "reason": "DUPLICATE_WALLET"})
            continue
        if score < min_score:
            rejected.append({"wallet": wallet, "reason": "WALLET_SCORE_TOO_LOW", "score": score})
            continue
        if len(accepted) >= max_wallets:
            rejected.append({"wallet": wallet, "reason": "WATCHLIST_LIMIT_REACHED", "score": score})
            continue
        seen.add(wallet)
        tags = tuple(str(tag) for tag in row.get("tags", ()) or ())
        accepted.append(WatchlistWallet(wallet=wallet, score=score, source=str(row.get("source") or "manual"), tags=tags))
    return SmartMoneyWatchlist(accepted=tuple(accepted), rejected=tuple(rejected))


__all__ = ["FULL_WALLET_RE", "SmartMoneyWatchlist", "WatchlistWallet", "build_smart_money_watchlist"]
