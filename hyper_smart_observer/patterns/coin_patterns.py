from __future__ import annotations


def favorite_coins(coins: list[str], limit: int = 5) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for coin in coins:
        counts[coin.upper()] = counts.get(coin.upper(), 0) + 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
