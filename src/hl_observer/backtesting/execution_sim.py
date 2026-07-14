"""Simulation d'exécution fine — pur, testé. Exécution du backlog :
queue_position (IDEA-16, place dans la file maker), tick_backtest (IDEA-59, backtest tick-by-tick).
No-lookahead. Aucun ordre réel, aucune promesse.
"""
from __future__ import annotations


def queue_position(order_price: float, book_side, *, side: str = "BUY") -> float:
    """Volume DEVANT ton ordre limite (priorité prix-temps) : tailles à prix meilleur ou égal.
    `book_side` : [(prix, taille)]."""
    op = float(order_price)
    ahead = 0.0
    for price, size in book_side:
        price = float(price)
        better = price > op if str(side).upper() == "BUY" else price < op
        if better or price == op:
            ahead += float(size)
    return ahead


def tick_backtest(prices, position_fn, *, cost_bps: float = 6.0, notional: float = 500.0) -> dict:
    """Backtest tick-by-tick. `position_fn(prices_jusqu_a_t)` -> position dans {-1,0,1} (no-lookahead).
    PnL = somme(position × rendement) ; coût facturé à chaque CHANGEMENT de position."""
    px = [float(p) for p in prices if float(p) > 0]
    pnl = costs = 0.0
    pos = 0
    for t in range(1, len(px)):
        new = int(position_fn(px[:t]))          # décision sur le passé uniquement
        if new != pos:
            costs += notional * cost_bps / 10000.0
            pos = new
        pnl += pos * (px[t] - px[t - 1]) / px[t - 1] * notional
    return {"net": round(pnl - costs, 4), "gross": round(pnl, 4), "costs": round(costs, 4)}
