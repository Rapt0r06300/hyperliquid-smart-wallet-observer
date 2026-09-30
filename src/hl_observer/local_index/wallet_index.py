from __future__ import annotations

import re
from dataclasses import dataclass, field

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(slots=True)
class IndexedWallet:
    wallet_address: str
    trades_count: int = 0
    closed_pnl_usdt: float = 0.0
    observed_notional_usdt: float = 0.0
    active_positions: int = 0
    last_seen_ms: int | None = None
    sources: set[str] = field(default_factory=set)

    @property
    def priority_hint(self) -> float:
        activity = min(30.0, self.trades_count * 0.3)
        pnl = max(-20.0, min(35.0, self.closed_pnl_usdt / 100.0))
        notional = min(20.0, self.observed_notional_usdt / 25_000.0)
        active = min(15.0, self.active_positions * 5.0)
        return round(max(0.0, activity + pnl + notional + active), 6)


class WalletLocalIndex:
    """In-memory fallback index used for fast local scans and tests."""

    def __init__(self) -> None:
        self._wallets: dict[str, IndexedWallet] = {}
        self.rejected: list[tuple[str, str]] = []

    def upsert(self, wallet: IndexedWallet) -> bool:
        address = str(wallet.wallet_address or "").strip()
        if "..." in address:
            self.rejected.append((address, "TRUNCATED_ADDRESS_REJECTED"))
            return False
        if not WALLET_RE.fullmatch(address):
            self.rejected.append((address, "INVALID_ADDRESS_REJECTED"))
            return False
        key = address.lower()
        existing = self._wallets.get(key)
        if existing is None:
            wallet.wallet_address = key
            self._wallets[key] = wallet
            return True
        existing.trades_count += wallet.trades_count
        existing.closed_pnl_usdt += wallet.closed_pnl_usdt
        existing.observed_notional_usdt += wallet.observed_notional_usdt
        existing.active_positions = max(existing.active_positions, wallet.active_positions)
        if wallet.last_seen_ms is not None:
            existing.last_seen_ms = max(existing.last_seen_ms or 0, wallet.last_seen_ms)
        existing.sources.update(wallet.sources)
        return True

    def scan(self, *, limit: int | None = None) -> list[IndexedWallet]:
        rows = sorted(self._wallets.values(), key=lambda row: row.priority_hint, reverse=True)
        if limit is not None:
            return rows[: max(0, int(limit))]
        return rows

    def __len__(self) -> int:
        return len(self._wallets)


def fake_wallet(index: int) -> IndexedWallet:  # fake-data-scan: allow deterministic local-index benchmark fixture (no market/PnL data, never in trading path)
    hex_part = f"{index:040x}"[-40:]
    return IndexedWallet(
        wallet_address=f"0x{hex_part}",
        trades_count=(index % 80) + 1,
        closed_pnl_usdt=float((index % 41) - 10) * 25.0,
        observed_notional_usdt=float((index % 200) + 1) * 1_000.0,
        active_positions=index % 4,
        last_seen_ms=1_800_000_000_000 - index,
        sources={"fake_local_benchmark"},
    )

