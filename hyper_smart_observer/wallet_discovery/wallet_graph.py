from __future__ import annotations


def build_wallet_coin_graph(wallet_coin_pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    graph: dict[str, set[str]] = {}
    for wallet, coin in wallet_coin_pairs:
        graph.setdefault(wallet.lower(), set()).add(coin.upper())
    return {wallet: sorted(coins) for wallet, coins in graph.items()}
