from __future__ import annotations

from hyper_smart_observer.explorer_observer.explorer_models import ExplorerEvent
from hyper_smart_observer.hyperliquid_client.validation import is_valid_wallet_address


def wallets_from_explorer_events(events: list[ExplorerEvent]) -> list[str]:
    seen: set[str] = set()
    wallets: list[str] = []
    for event in events:
        if event.user and is_valid_wallet_address(event.user) and event.user.lower() not in seen:
            seen.add(event.user.lower())
            wallets.append(event.user.lower())
    return wallets
