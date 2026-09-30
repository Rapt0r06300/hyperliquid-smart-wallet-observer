from __future__ import annotations

from hyper_smart_observer.hyperliquid_client.models import Wallet, WalletStatus


def shortlist_wallets(wallets: list[Wallet], limit: int = 100) -> list[Wallet]:
    return [
        Wallet(
            address=wallet.address,
            label=wallet.label,
            source=wallet.source,
            discovered_at=wallet.discovered_at,
            status=WalletStatus.SHORTLISTED,
            notes=wallet.notes,
        )
        for wallet in wallets[: max(0, limit)]
    ]
