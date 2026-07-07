"""I1-I5 — Métriques étendues : Sharpe/Sortino/Calmar + attribution + MAE/MFE + hit rate.
Complète le profit factor du juge. Pur.
"""

from __future__ import annotations


def sharpe(returns, *, rf: float = 0.0) -> float:
    r = [float(x) - rf for x in returns]
    n = len(r)
    if n < 2:
        return 0.0
    mean = sum(r) / n
    var = sum((x - mean) ** 2 for x in r) / (n - 1)
    sd = var ** 0.5
    return round(mean / sd, 6) if sd > 0 else 0.0


def sortino(returns, *, rf: float = 0.0) -> float:
    r = [float(x) - rf for x in returns]
    n = len(r)
    if n < 2:
        return 0.0
    mean = sum(r) / n
    downside = [x for x in r if x < 0]
    if not downside:
        return float("inf")
    dd = (sum(x * x for x in downside) / len(downside)) ** 0.5
    return round(mean / dd, 6) if dd > 0 else 0.0


def calmar(total_return: float, max_drawdown: float) -> float:
    if max_drawdown <= 0:
        return 0.0
    return round(float(total_return) / float(max_drawdown), 6)


def attribution_by(trades, key: str, *, pnl_key: str = "pnl") -> dict:
    """PnL agrégé par clé (coin, leader...), trié croissant (les pires d'abord)."""
    out: dict = {}
    for t in trades:
        k = t.get(key)
        out[k] = out.get(k, 0.0) + float(t.get(pnl_key, 0.0))
    return dict(sorted(out.items(), key=lambda kv: kv[1]))


def mae_mfe_stats(trades) -> dict:
    maes = [float(t.get("mae_bps", 0.0)) for t in trades]
    mfes = [float(t.get("mfe_bps", 0.0)) for t in trades]

    def _avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    return {"avg_mae_bps": _avg(maes), "avg_mfe_bps": _avg(mfes), "n": len(trades)}


def hit_rate_expectancy(pnls) -> dict:
    vals = [float(p) for p in pnls]
    n = len(vals)
    wins = [p for p in vals if p > 0]
    losses = [p for p in vals if p < 0]
    return {
        "hit_rate": round(len(wins) / n, 4) if n else 0.0,
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "expectancy": round(sum(vals) / n, 6) if n else 0.0,
    }


__all__ = ["sharpe", "sortino", "calmar", "attribution_by", "mae_mfe_stats", "hit_rate_expectancy"]
