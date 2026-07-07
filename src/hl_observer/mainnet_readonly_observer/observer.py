from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient
from hl_observer.testnet.models import unix_ms


@dataclass(frozen=True, slots=True)
class MainnetObservation:
    source: str
    all_mids: dict[str, float]
    l2_books: dict[str, dict[str, Any]] = field(default_factory=dict)
    wallet_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    wallet_fills: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    observed_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MainnetReadOnlyObserver:
    """Reads Hyperliquid mainnet public/read-only data only."""

    def __init__(self, client: HyperliquidInfoClient | None = None) -> None:
        self.client = client or HyperliquidInfoClient()

    async def observe(
        self,
        *,
        coins: list[str] | None = None,
        wallets: list[str] | None = None,
        include_l2: bool = True,
        include_wallet_fills: bool = False,
    ) -> MainnetObservation:
        errors: list[str] = []
        mids: dict[str, float] = {}
        l2_books: dict[str, dict[str, Any]] = {}
        wallet_states: dict[str, dict[str, Any]] = {}
        wallet_fills: dict[str, list[dict[str, Any]]] = {}

        try:
            raw_mids = await self.client.all_mids()
            mids = {str(coin).upper(): float(price) for coin, price in raw_mids.items()}
        except Exception as exc:  # noqa: BLE001 - observer must return honest partial state.
            errors.append(f"all_mids_failed:{exc}")

        selected_coins = [coin.upper() for coin in (coins or list(mids.keys())[:5])]
        if include_l2:
            for coin in selected_coins:
                try:
                    l2_books[coin] = await self.client.l2_book(coin)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"l2_book_failed:{coin}:{exc}")

        for wallet in wallets or []:
            try:
                wallet_states[wallet] = await self.client.clearinghouse_state(wallet)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"clearinghouse_state_failed:{wallet}:{exc}")
            if include_wallet_fills:
                try:
                    wallet_fills[wallet] = await self.client.user_fills(wallet)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"user_fills_failed:{wallet}:{exc}")

        return MainnetObservation(
            source="hyperliquid_mainnet_readonly",
            all_mids=mids,
            l2_books=l2_books,
            wallet_states=wallet_states,
            wallet_fills=wallet_fills,
            errors=errors,
        )
