"""Zoo de mecanismes simples pour un SCAN honnete, tous sur la meme serie de prix, memes couts reels,
meme forme de rapport. Pur, no-lookahead, paper-only, aucun ordre.

Familles : momentum (suivi de tendance), breakout (cassure), reversion (via mean_reversion),
buy&hold (baseline), et ALEATOIRE (le controle). Le hasard est essentiel : si la meilleure strategie
ne bat pas clairement le MEILLEUR des tirages aleatoires, son "edge" est du bruit (comparaisons
multiples). Aucune promesse de PnL.
"""
from __future__ import annotations

import random as _random


def _report(trades) -> dict:
    wins = [t for t in trades if t > 0]
    gl = -sum(t for t in trades if t < 0)
    gw = sum(wins)
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": len(trades), "net_usd": round(sum(trades), 2),
            "win_rate": round(len(wins) / len(trades), 4) if trades else None,
            "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
            "max_drawdown_usd": round(dd, 2)}


def _pnl(side, entry, exitp, cost_bps, notional):
    ret = (exitp - entry) / entry if side == "LONG" else (entry - exitp) / entry
    return notional * ret - notional * cost_bps / 10000.0


def _clean(px):
    return [float(p) for p in px if float(p) > 0]


def momentum(px, *, lookback=30, hold=30, cost_bps=6.0, notional=500.0) -> dict:
    px = _clean(px); n = len(px); trades = []; i = lookback
    while i < n - 1:
        side = "LONG" if px[i] > px[i - lookback] else "SHORT"
        j = min(n - 1, i + hold)
        trades.append(_pnl(side, px[i], px[j], cost_bps, notional))
        i = j + 1
    return _report(trades)


def breakout(px, *, lookback=30, hold=30, cost_bps=6.0, notional=500.0) -> dict:
    px = _clean(px); n = len(px); trades = []; i = lookback
    while i < n - 1:
        window = px[i - lookback:i]
        side = "LONG" if px[i] > max(window) else ("SHORT" if px[i] < min(window) else None)
        if side is None:
            i += 1
            continue
        j = min(n - 1, i + hold)
        trades.append(_pnl(side, px[i], px[j], cost_bps, notional))
        i = j + 1
    return _report(trades)


def buy_hold(px, *, cost_bps=6.0, notional=500.0) -> dict:
    px = _clean(px)
    if len(px) < 2:
        return _report([])
    return _report([_pnl("LONG", px[0], px[-1], cost_bps, notional)])


def random_strategy(px, *, seed=0, hold=30, p_trade=0.1, cost_bps=6.0, notional=500.0) -> dict:
    """Controle : entrees et sens ALEATOIRES. Sert de reference 'bruit'."""
    px = _clean(px); n = len(px); rng = _random.Random(seed); trades = []; i = 1
    while i < n - 1:
        if rng.random() < p_trade:
            side = "LONG" if rng.random() < 0.5 else "SHORT"
            j = min(n - 1, i + hold)
            trades.append(_pnl(side, px[i], px[j], cost_bps, notional))
            i = j + 1
        else:
            i += 1
    return _report(trades)
