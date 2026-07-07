"""VALID-2 — Baselines de vérité: bat-on "ne rien faire" et "acheter-garder BTC" ?

La seule question qui compte. Si la stratégie ne bat pas ces deux courbes, tout le
reste est cosmétique. Pur, honnête: mêmes bornes temporelles, aucun avantage
informationnel donné aux baselines.
"""

from __future__ import annotations


def no_trade_baseline(starting_equity_usdt: float, n_points: int) -> list[float]:
    """Ne rien faire: equity plate."""
    return [round(float(starting_equity_usdt), 6)] * max(1, int(n_points))


def hold_btc_baseline(starting_equity_usdt: float, btc_prices: list[float]) -> list[float]:
    """Acheter BTC à t0 avec tout le capital, garder: equity = capital × prix/prix0."""
    clean = [float(p) for p in (btc_prices or []) if _pos(p)]
    if not clean:
        return [round(float(starting_equity_usdt), 6)]
    p0 = clean[0]
    return [round(float(starting_equity_usdt) * (p / p0), 6) for p in clean]


def compare_to_baselines(strategy_equity: list[float], *, starting_equity_usdt: float, btc_prices: list[float]) -> dict:
    """Compare la courbe stratégie aux baselines sur le même nombre de points."""

    strat = [float(x) for x in (strategy_equity or []) if _num(x)]
    if len(strat) < 2:
        return {"verdict": "INSUFFICIENT_STRATEGY_HISTORY", "n": len(strat)}
    n = len(strat)
    nt = no_trade_baseline(starting_equity_usdt, n)
    hb = hold_btc_baseline(starting_equity_usdt, btc_prices)
    hb = (hb + [hb[-1]] * n)[:n] if hb else nt   # aligner la longueur honnêtement
    strat_ret = strat[-1] - strat[0]
    nt_ret = nt[-1] - nt[0]
    hb_ret = hb[-1] - hb[0]
    return {
        "verdict": "OK",
        "n": n,
        "strategy_return_usdt": round(strat_ret, 6),
        "no_trade_return_usdt": round(nt_ret, 6),
        "hold_btc_return_usdt": round(hb_ret, 6),
        "beats_no_trade": strat_ret > nt_ret,
        "beats_hold_btc": strat_ret > hb_ret,
        "beats_both": strat_ret > nt_ret and strat_ret > hb_ret,
        "excess_vs_no_trade_usdt": round(strat_ret - nt_ret, 6),
        "excess_vs_hold_btc_usdt": round(strat_ret - hb_ret, 6),
        "honesty": "same window, no informational edge given to baselines; not a PnL promise",
    }


def _pos(x) -> bool:
    try:
        return float(x) > 0
    except (TypeError, ValueError):
        return False


def _num(x) -> bool:
    try:
        float(x); return True
    except (TypeError, ValueError):
        return False


__all__ = ["no_trade_baseline", "hold_btc_baseline", "compare_to_baselines"]
