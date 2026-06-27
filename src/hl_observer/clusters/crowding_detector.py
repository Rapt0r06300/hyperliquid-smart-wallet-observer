from __future__ import annotations


def crowding_score(active_wallets_same_side: int, max_comfortable_wallets: int = 5) -> float:
    if max_comfortable_wallets <= 0:
        return 1.0
    return min(1.0, active_wallets_same_side / max_comfortable_wallets)
