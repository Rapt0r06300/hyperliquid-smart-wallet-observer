from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(slots=True)
class WalletAggregate:
    wallet_address: str
    events: int = 0
    closed_pnl: float = 0.0
    notional: float = 0.0
    coins: set[str] = field(default_factory=set)


class IncrementalAggregator:
    def __init__(self) -> None:
        self.wallets: dict[str, WalletAggregate] = {}
        self.coin_counts: dict[str, int] = defaultdict(int)

    def add_event(self, event: dict) -> None:
        wallet = str(event.get("wallet") or event.get("wallet_address") or "").lower()
        if not wallet:
            return
        coin = str(event.get("coin") or "UNKNOWN").upper()
        aggregate = self.wallets.setdefault(wallet, WalletAggregate(wallet_address=wallet))
        aggregate.events += 1
        aggregate.closed_pnl += float(event.get("closed_pnl", 0.0) or 0.0)
        aggregate.notional += float(event.get("notional", 0.0) or 0.0)
        aggregate.coins.add(coin)
        self.coin_counts[coin] += 1

    def add_chunk(self, rows: list[dict]) -> None:
        for row in rows:
            self.add_event(row)
