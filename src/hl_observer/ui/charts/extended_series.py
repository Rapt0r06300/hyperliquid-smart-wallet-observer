"""V13 #160 — Séries de charts étendues (pm-backtest A3) : equity par coin, allocation,
rendements mensuels, avantage Brier cumulé. Pures ; aucun point inventé (vide -> vide)."""

from __future__ import annotations

from datetime import datetime, timezone


def equity_by_coin(closed_trades: list[dict]) -> dict:
    """{coin: [{time, value}]} = PnL cumulé par coin dans le temps. closed_trades: {coin, close_ts_ms, net_pnl_usdc}."""
    by_coin: dict[str, list[dict]] = {}
    for t in sorted(closed_trades or [], key=lambda x: int(x.get("close_ts_ms") or 0)):
        coin = str(t.get("coin") or "?").upper()
        cum = (by_coin[coin][-1]["value"] if by_coin.get(coin) else 0.0) if coin in by_coin else 0.0
        by_coin.setdefault(coin, [])
        cum = (by_coin[coin][-1]["value"] if by_coin[coin] else 0.0) + float(t.get("net_pnl_usdc") or 0.0)
        by_coin[coin].append({"time": int(int(t.get("close_ts_ms") or 0) / 1000), "value": round(cum, 6)})
    return by_coin


def market_allocation(positions: list[dict]) -> list[dict]:
    raw: dict[str, float] = {}
    for p in positions or []:
        coin = str(p.get("coin") or "?").upper()
        raw[coin] = raw.get(coin, 0.0) + abs(float(p.get("notional_usdt") or p.get("open_exposure_usdt") or 0.0))
    total = sum(raw.values())
    if total <= 0:
        return []
    return sorted(({"coin": c, "weight": round(v / total, 4)} for c, v in raw.items()),
                  key=lambda d: -d["weight"])


def monthly_returns(equity_points: list[dict]) -> list[dict]:
    """equity_points: [{time(sec), equity}] -> [{month 'YYYY-MM', return_pct}] (vide -> vide)."""
    by_month: dict[str, list[float]] = {}
    for p in sorted(equity_points or [], key=lambda x: int(x.get("time") or 0)):
        if "equity" not in p:
            continue
        ym = datetime.fromtimestamp(int(p["time"]), tz=timezone.utc).strftime("%Y-%m")
        by_month.setdefault(ym, []).append(float(p["equity"]))
    out = []
    for ym in sorted(by_month):
        vals = by_month[ym]
        if len(vals) >= 2 and vals[0] > 0:
            out.append({"month": ym, "return_pct": round((vals[-1] - vals[0]) / vals[0] * 100.0, 4)})
    return out


def cumulative_brier_advantage_series(items: list[dict], *, baseline: float = 0.5) -> list[dict]:
    """items: [{time, model_p, outcome}] -> avantage Brier cumulé moyen dans le temps."""
    seq = sorted(items or [], key=lambda x: int(x.get("time") or 0))
    out, sm, sb, n = [], 0.0, 0.0, 0
    for it in seq:
        try:
            p = min(1.0, max(0.0, float(it["model_p"])))
            y = 1.0 if it.get("outcome") else 0.0
        except (KeyError, TypeError, ValueError):
            continue
        sm += (p - y) ** 2
        sb += (baseline - y) ** 2
        n += 1
        out.append({"time": int(it.get("time") or 0), "value": round((sb - sm) / n, 6)})  # >0 = bat le hasard
    return out


__all__ = ["equity_by_coin", "market_allocation", "monthly_returns", "cumulative_brier_advantage_series"]
