"""Stratégies supplémentaires — pures, testées. Exécution du backlog :
pairs_trade_signal (IMPROVE-37, cointégration), rebalancing_premium (IMPROVE-39, capture de
volatilité / 'volatility pumping'), cross_market_momentum (IMPROVE-40, BTC comme signal avancé).
Aucune promesse de PnL — outils d'exploration honnête, coûts inclus. Aucun ordre.
"""
from __future__ import annotations

from hl_observer.backtesting.signal_processing import engle_granger_spread


def pairs_trade_signal(a, b, *, entry_z: float = 2.0, exit_z: float = 0.5) -> dict:
    """Signal de pairs trading : quand le spread cointégré s'écarte, parier sur son retour.
    +1 = long A / short B ; -1 = l'inverse ; 0 = pas de position."""
    r = engle_granger_spread(a, b)
    sp = r["spread"]
    if len(sp) < 3:
        return {"signal": 0, "z": 0.0, "beta": r["beta"]}
    m = sum(sp) / len(sp)
    sd = (sum((s - m) ** 2 for s in sp) / len(sp)) ** 0.5
    z = (sp[-1] - m) / sd if sd > 0 else 0.0
    sig = 0
    if z <= -entry_z:
        sig = 1
    elif z >= entry_z:
        sig = -1
    return {"signal": sig, "z": z, "beta": r["beta"]}


def rebalancing_premium(prices_a, prices_b, *, weight_a: float = 0.5, rebalance_every: int = 10) -> dict:
    """Capture de volatilité par REBALANCEMENT ('volatility pumping'). Compare la valeur finale d'un
    portefeuille rebalancé vs buy&hold. Le premium vient de la volatilité, pas d'une prédiction."""
    a = [float(p) for p in prices_a]
    b = [float(p) for p in prices_b]
    n = min(len(a), len(b))
    if n < 2 or a[0] <= 0 or b[0] <= 0:
        return {"rebalanced": 1.0, "buyhold": 1.0, "premium": 0.0}
    bh = weight_a * (a[n - 1] / a[0]) + (1 - weight_a) * (b[n - 1] / b[0])
    val = 1.0
    ua = val * weight_a / a[0]
    ub = val * (1 - weight_a) / b[0]
    for t in range(1, n):
        val = ua * a[t] + ub * b[t]
        if t % max(1, int(rebalance_every)) == 0 and a[t] > 0 and b[t] > 0:
            ua = val * weight_a / a[t]
            ub = val * (1 - weight_a) / b[t]
    return {"rebalanced": round(val, 6), "buyhold": round(bh, 6), "premium": round(val - bh, 6)}


def cross_market_momentum(leader_prices, follower_prices, *, lookback: int = 20, hold: int = 10,
                          cost_bps: float = 6.0, notional: float = 500.0) -> dict:
    """Le momentum du LEADER (ex : BTC) prédit-il le FOLLOWER (alt) ? Testé avec coûts réels."""
    la = [float(p) for p in leader_prices]
    fo = [float(p) for p in follower_prices]
    n = min(len(la), len(fo))
    trades = []
    i = lookback
    while i < n - 1:
        side = "LONG" if la[i] > la[i - lookback] else "SHORT"
        j = min(n - 1, i + hold)
        if fo[i] > 0:
            ret = (fo[j] - fo[i]) / fo[i] if side == "LONG" else (fo[i] - fo[j]) / fo[i]
            trades.append(notional * ret - notional * cost_bps / 10000.0)
        i = j + 1
    return {"trades": len(trades), "net_usd": round(sum(trades), 2)}
