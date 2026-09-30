from __future__ import annotations


def cluster_wallets_by_coin(wallet_to_coins: dict[str, set[str]]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = {}
    for wallet, coins in wallet_to_coins.items():
        key = ",".join(sorted(coins)) or "unknown"
        clusters.setdefault(key, []).append(wallet)
    return clusters
