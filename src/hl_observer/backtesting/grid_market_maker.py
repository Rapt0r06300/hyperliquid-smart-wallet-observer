"""Simulateur de grid / market-making 'grinder' (style passivbot) sur de VRAIS chemins de prix.

But HONNETE : mesurer le compromis du grinder — beaucoup de petits gains en marche range, MAIS
risque de QUEUE quand une position se retrouve 'coincee' en tendance (stop dur = grosse perte). On
NE cache PAS le tail : on compte les blow-ups, le drawdown, et on marque l'inventaire ouvert a la fin.

Long-biais (profil par defaut passivbot). add_size_mult : 1.0 = grid a taille constante ;
> 1.0 = martingale (double la mise -> amplifie le tail). Pur, deterministe, paper-only, aucun ordre.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GridConfig:
    grid_bps: float = 30.0        # espacement entre ajouts
    tp_bps: float = 30.0          # take-profit au-dessus de l'entree MOYENNE
    max_adds: int = 6             # nb max d'ajouts (paliers)
    base_size_usd: float = 50.0   # taille du 1er palier
    add_size_mult: float = 1.0    # 1.0 = grid ; 2.0 = martingale (double a chaque ajout)
    hard_stop_bps: float = 300.0  # excursion adverse max avant stop dur (le TAIL)
    fee_bps: float = 1.0          # maker par fill
    adverse_bps: float = 0.0      # cout de selection adverse par fill (0=optimiste, 2-5=realiste)


def simulate_grid(prices, cfg: GridConfig) -> dict:
    px = [float(p) for p in prices if float(p) > 0]
    n = len(px)
    empty = {"prices": n, "net_usd": 0.0, "wins": 0, "blowups": 0, "adds": 0,
             "max_drawdown_usd": 0.0, "fees_usd": 0.0, "open_notional_usd": 0.0}
    if n < 3:
        return empty

    total_units = 0.0
    total_cost = 0.0
    adds = 0
    last_add_price = None
    realized = 0.0
    fees = 0.0
    wins = 0
    blowups = 0
    peak = 0.0
    max_dd = 0.0

    def avg():
        return total_cost / total_units if total_units > 0 else 0.0

    def add(p):
        nonlocal total_units, total_cost, adds, last_add_price, fees
        size = cfg.base_size_usd * (cfg.add_size_mult ** adds)
        total_units += size / p
        total_cost += size
        fees += size * (cfg.fee_bps + cfg.adverse_bps) / 10000.0
        adds += 1
        last_add_price = p

    def close(p):
        nonlocal total_units, total_cost, adds, last_add_price, realized, fees
        ae = avg()
        realized += total_units * (p - ae)
        fees += total_units * p * (cfg.fee_bps + cfg.adverse_bps) / 10000.0
        total_units = 0.0
        total_cost = 0.0
        adds = 0
        last_add_price = None

    add(px[0])
    for p in px[1:]:
        if total_units <= 0:
            add(p)
            continue
        ae = avg()
        if p >= ae * (1.0 + cfg.tp_bps / 10000.0):
            close(p)
            wins += 1
            add(p)
        elif p <= ae * (1.0 - cfg.hard_stop_bps / 10000.0):
            close(p)
            blowups += 1
            add(p)
        elif adds < cfg.max_adds and last_add_price and p <= last_add_price * (1.0 - cfg.grid_bps / 10000.0):
            add(p)
        equity = realized + total_units * (p - avg()) - fees
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    final_unreal = total_units * (px[-1] - avg()) if total_units > 0 else 0.0
    net = realized + final_unreal - fees
    return {"prices": n, "net_usd": round(net, 2), "wins": wins, "blowups": blowups, "adds": adds,
            "max_drawdown_usd": round(max_dd, 2), "fees_usd": round(fees, 2),
            "open_notional_usd": round(total_cost, 2)}
