from __future__ import annotations


def stability_adjusted_score(net_pnl: float, max_drawdown: float) -> float:
    return net_pnl - abs(max_drawdown)
