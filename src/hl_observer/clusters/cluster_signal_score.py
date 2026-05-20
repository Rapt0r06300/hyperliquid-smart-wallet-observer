from __future__ import annotations


def cluster_confirmation_bps(wallets_confirming: int, max_bonus_bps: float = 5.0) -> float:
    return min(max_bonus_bps, max(0, wallets_confirming - 1) * 1.5)
