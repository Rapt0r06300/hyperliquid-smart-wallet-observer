"""O2 + O3 + O4 — Monte Carlo de l'equity, stabilité des paramètres, perf par régime.

O2 : un backtest = UN tirage. En rééchantillonnant l'ordre des trades (bootstrap), on obtient un
INTERVALLE de confiance sur le PnL et le drawdown — le vrai risque, pas un chiffre unique flatteur.
O3 : un bon paramètre est entouré de BONS paramètres (plateau), pas un pic isolé (overfit).
O4 : perf ventilée par régime (où l'edge vit / meurt). PUR (random seedable). PAPER only.
"""
from __future__ import annotations

import random
from typing import Mapping, Sequence

from hl_observer.backtesting.perf_metrics import max_drawdown, panel


def _percentile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    i = max(0, min(len(s) - 1, int(q * len(s))))
    return s[i]


def bootstrap_equity(pnls: Sequence[float], *, n_sim: int = 1000, rng: random.Random | None = None) -> dict | None:
    """Rééchantillonne les trades AVEC remise -> intervalles sur PnL total et max drawdown."""
    xs = [float(x) for x in pnls or []]
    if len(xs) < 5:
        return None
    r = rng or random.Random(0)
    totals, dds = [], []
    for _ in range(int(n_sim)):
        echant = [r.choice(xs) for _ in range(len(xs))]
        totals.append(sum(echant))
        dds.append(max_drawdown(echant))
    return {"pnl_median": round(_percentile(totals, 0.5), 6),
            "pnl_p05": round(_percentile(totals, 0.05), 6),
            "pnl_p95": round(_percentile(totals, 0.95), 6),
            "drawdown_p95": round(_percentile(dds, 0.95), 6),
            "prob_pnl_negatif": round(sum(1 for t in totals if t < 0) / len(totals), 4)}


def stabilite_parametre(perf_par_param: Mapping[float, float], *, fraction_plateau: float = 0.7) -> dict | None:
    """Le meilleur paramètre est-il sur un PLATEAU (voisins ~aussi bons) ou un pic isolé (overfit) ?"""
    if not perf_par_param:
        return None
    items = sorted(((float(k), float(v)) for k, v in perf_par_param.items()), key=lambda kv: kv[0])
    i_best = max(range(len(items)), key=lambda i: items[i][1])
    best = items[i_best][1]
    voisins = [items[j][1] for j in (i_best - 1, i_best + 1) if 0 <= j < len(items)]
    plateau = bool(voisins) and best > 0 and all(v >= float(fraction_plateau) * best for v in voisins)
    return {"meilleur_param": items[i_best][0], "meilleure_perf": round(best, 6),
            "plateau": plateau}


def perf_par_regime(pnls_par_regime: Mapping[str, Sequence[float]]) -> dict:
    """O4 : panel de métriques par régime (où l'edge vit / meurt)."""
    return {str(reg): panel(list(pnls)) for reg, pnls in (pnls_par_regime or {}).items()}


__all__ = ["bootstrap_equity", "stabilite_parametre", "perf_par_regime"]
