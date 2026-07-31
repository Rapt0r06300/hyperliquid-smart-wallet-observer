"""ALPHA P21 — modèle microstructure UNIVERSEL (pooled) + validation LEAVE-ONE-COIN-OUT.

On normalise une feature entre coins puis on ajuste UN modèle pooled (régression simple feature→target) sur
tous les coins SAUF un, et on teste sur le coin exclu. Un signal qui transfère (net OOS positif sur le coin
jamais vu) vaut bien plus qu'un signal sur-ajusté à un coin. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any


def _zscore(v: Sequence[float]) -> list[float]:
    if len(v) < 2:
        return [0.0] * len(v)
    m = statistics.mean(v)
    s = statistics.pstdev(v) or 1.0
    return [(x - m) / s for x in v]


def _fit(x: Sequence[float], y: Sequence[float]) -> float:
    n = min(len(x), len(y))
    if n < 5:
        return 0.0
    mx = sum(x[:n]) / n; my = sum(y[:n]) / n
    sxx = sum((x[i] - mx) ** 2 for i in range(n))
    if sxx <= 0:
        return 0.0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / sxx


def leave_one_coin_out(par_coin: Mapping[str, tuple[Sequence[float], Sequence[float]]], *,
                       cout_bps: float = 9.0) -> dict[str, Any]:
    """par_coin[coin] = (feature, target_bps). Fit pooled sur N-1 coins, teste sur le coin exclu. Net OOS moyen."""
    coins = [c for c, (f, t) in par_coin.items() if len(f) >= 20]
    if len(coins) < 2:
        return {"verdict": "MORE_DATA", "n_coins": len(coins)}
    nets = {}
    for held in coins:
        xs, ys = [], []
        for c in coins:
            if c == held:
                continue
            f, t = par_coin[c]
            xs += _zscore(f); ys += list(t)
        pente = _fit(xs, ys)
        fh, th = par_coin[held]
        zf = _zscore(fh)
        # markout : direction = signe(pente*feature), net = direction*target - cout
        nets_held = []
        for i in range(len(zf)):
            d = 1.0 if pente * zf[i] > 0 else -1.0
            nets_held.append(d * th[i] - cout_bps)
        nets[held] = round(sum(nets_held) / len(nets_held), 4) if nets_held else None
    mesurables = [v for v in nets.values() if v is not None]
    net_moyen = round(sum(mesurables) / len(mesurables), 4) if mesurables else None
    verdict = "MORE_DATA" if net_moyen is None else ("TRANSFERABLE_A_OOS" if net_moyen > 0 else "KILL")
    return {"net_oos_par_coin": nets, "net_oos_moyen_bps": net_moyen, "verdict": verdict, "n_coins": len(coins)}


__all__ = ["leave_one_coin_out"]
