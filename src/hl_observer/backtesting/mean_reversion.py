"""Backtest de REVERSION A LA MOYENNE — mecanisme GENUINEMENT DIFFERENT du copy-trading.

Idee : quand le prix s'ecarte fortement de sa moyenne mobile (z-score eleve), parier sur le retour
vers la moyenne. Ni baleines, ni copie — une propriete statistique du prix lui-meme.

Honnete : no-lookahead (le z a l'instant t n'utilise que les prix <= t), couts reels appliques par
trade. Aucune promesse : la reversion gagne en marche range et PERD en tendance (le prix "pas cher"
continue de baisser). Pur, deterministe, paper-only, aucun ordre.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pstdev


@dataclass(frozen=True, slots=True)
class MRConfig:
    lookback: int = 40          # taille de la fenetre pour moyenne/ecart-type
    entry_z: float = 2.0        # on entre quand |z| depasse ce seuil
    exit_z: float = 0.3         # on sort quand le z est revenu sous ce seuil (reversion faite)
    hard_stop_z: float = 4.0    # stop si le z s'aggrave (la tendance continue) = le TAIL
    hold_max: int = 60          # duree max de detention (en pas)
    cost_bps: float = 6.0       # cout aller-retour (frais + spread + slippage), taker
    notional_usd: float = 500.0


def _z(window, price):
    m = fmean(window)
    sd = pstdev(window)
    return (price - m) / sd if sd > 0 else 0.0


def simulate_mean_reversion(prices, cfg: MRConfig) -> dict:
    px = [float(p) for p in prices if float(p) > 0]
    n = len(px)
    if n < cfg.lookback + 5:
        return {"trades": 0, "net_usd": 0.0, "win_rate": None, "profit_factor": 0.0,
                "max_drawdown_usd": 0.0}
    trades = []
    i = cfg.lookback
    while i < n - 1:
        z = _z(px[i - cfg.lookback:i], px[i])
        side = "LONG" if z <= -cfg.entry_z else ("SHORT" if z >= cfg.entry_z else None)
        if side is None:
            i += 1
            continue
        entry = px[i]
        exit_px = px[min(n - 1, i + cfg.hold_max)]
        exit_i = min(n - 1, i + cfg.hold_max)
        for j in range(i + 1, min(n, i + 1 + cfg.hold_max)):
            zj = _z(px[j - cfg.lookback:j], px[j])
            reverted = (side == "LONG" and zj >= -cfg.exit_z) or (side == "SHORT" and zj <= cfg.exit_z)
            stopped = (side == "LONG" and zj <= -cfg.hard_stop_z) or (side == "SHORT" and zj >= cfg.hard_stop_z)
            if reverted or stopped:
                exit_px = px[j]
                exit_i = j
                break
        ret = (exit_px - entry) / entry if side == "LONG" else (entry - exit_px) / entry
        pnl = cfg.notional_usd * ret - cfg.notional_usd * cfg.cost_bps / 10000.0
        trades.append(pnl)
        i = exit_i + 1  # pas de chevauchement de positions

    wins = [t for t in trades if t > 0]
    gl = -sum(t for t in trades if t < 0)
    gw = sum(wins)
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "trades": len(trades),
        "net_usd": round(sum(trades), 2),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
        "max_drawdown_usd": round(dd, 2),
    }
