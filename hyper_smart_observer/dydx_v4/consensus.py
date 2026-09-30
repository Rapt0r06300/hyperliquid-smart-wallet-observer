"""
Consensus gate — confluence multi-wallets (la seule entrée qui marche
selon la recherche sur les copy-bots: la copie naïve 1-wallet sous-performe
le wallet source de 60-80% de son PnL net).

Règle: un signal d'entrée n'est valide que si ≥K comptes SHORTLISTÉS
distincts ouvrent le même marché dans le même sens dans une fenêtre donnée.

PAPER-ONLY / READ-ONLY. Un signal n'est jamais un ordre.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_MS = 10 * 60 * 1000  # 10 minutes
DEFAULT_MIN_WALLETS = 2


@dataclass
class ConsensusEntry:
    account_key: str
    market_id: str
    side: str
    ts_ms: int
    notional_usdc: float = 0.0


@dataclass
class ConsensusResult:
    met: bool
    distinct_accounts: int
    required: int
    window_ms: int
    accounts: list[str] = field(default_factory=list)
    total_notional_usdc: float = 0.0
    first_ts_ms: int = 0
    last_ts_ms: int = 0


class ConsensusTracker:
    """
    Buffer glissant des ouvertures récentes par (market, side).

    Usage:
        tracker.record_open(account, market, side, ts, notional)
        result = tracker.check(market, side, now_ms)
        if not result.met: NO_TRADE(CONSENSUS_NOT_REACHED)
    """

    def __init__(
        self,
        min_wallets: int = DEFAULT_MIN_WALLETS,
        window_ms: int = DEFAULT_WINDOW_MS,
        max_entries: int = 10_000,
    ) -> None:
        self.min_wallets = max(1, int(min_wallets))
        self.window_ms = max(1_000, int(window_ms))
        self.max_entries = max_entries
        self._entries: list[ConsensusEntry] = []

    def record_open(
        self,
        account_key: str,
        market_id: str,
        side: str,
        ts_ms: int | None = None,
        notional_usdc: float = 0.0,
    ) -> None:
        """Enregistrer une ouverture (OPEN/ADD) d'un compte shortlisté."""
        ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
        self._entries.append(
            ConsensusEntry(account_key, market_id, side.upper(), ts, notional_usdc)
        )
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries // 2:]

    def _prune(self, now_ms: int) -> None:
        cutoff = now_ms - self.window_ms
        self._entries = [e for e in self._entries if e.ts_ms >= cutoff]

    def check(
        self,
        market_id: str,
        side: str,
        now_ms: int | None = None,
        min_wallets: int | None = None,
    ) -> ConsensusResult:
        """Le consensus est-il atteint pour (market, side) dans la fenêtre ?"""
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        required = min_wallets if min_wallets is not None else self.min_wallets
        self._prune(now)

        side_u = side.upper()
        matching = [
            e for e in self._entries
            if e.market_id == market_id and e.side == side_u
        ]
        by_account: dict[str, ConsensusEntry] = {}
        for e in matching:
            by_account[e.account_key] = e

        distinct = len(by_account)
        met = distinct >= required
        ts_list = [e.ts_ms for e in by_account.values()] or [0]
        return ConsensusResult(
            met=met,
            distinct_accounts=distinct,
            required=required,
            window_ms=self.window_ms,
            accounts=sorted(by_account),
            total_notional_usdc=sum(e.notional_usdc for e in by_account.values()),
            first_ts_ms=min(ts_list),
            last_ts_ms=max(ts_list),
        )

    def clear(self) -> None:
        self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)
