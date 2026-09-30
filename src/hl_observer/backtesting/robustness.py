"""Outils de robustesse HONNETES pour le replay (aucune promesse de PnL).

- profit_factor        : gains bruts / pertes brutes.
- bootstrap_pnl_ci     : intervalle de confiance sur le PnL net par reechantillonnage (avec remise)
                         de la sequence de trades. Un net median ~0 avec un p05 tres negatif =
                         resultat FRAGILE (bruit), pas un edge. Repond a "est-ce de la chance ?".
- maker_adjust_net     : modelise une entree MAKER (economise le spread) MAIS avec risque de
                         missed-fill (tous les trades ne se remplissent pas). 'adverse' = version
                         pessimiste honnete (les gagnants filent, on ne remplit que les moins bons).

Fonctions PURES et deterministes (seed). Lecture seule, aucun ordre, aucune execution reelle.
"""
from __future__ import annotations

import random
from statistics import median


def profit_factor(trades) -> float:
    gw = sum(t for t in trades if t > 0)
    gl = -sum(t for t in trades if t < 0)
    if gl <= 0:
        return float("inf") if gw > 0 else 0.0
    return gw / gl


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    idx = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    return sorted_vals[min(len(sorted_vals) - 1, max(0, idx))]


def bootstrap_pnl_ci(trades, *, n=2000, seed=7, lo=5, hi=95) -> dict:
    """Reechantillonne la sequence de trades n fois (avec remise) -> distribution du net total."""
    xs = [float(t) for t in trades]
    if not xs:
        return {"trades": 0}
    rng = random.Random(seed)
    k = len(xs)
    nets = []
    for _ in range(int(n)):
        s = 0.0
        for _ in range(k):
            s += xs[rng.randrange(k)]
        nets.append(s)
    nets.sort()
    return {
        "trades": k,
        "net_observed": round(sum(xs), 2),
        "net_median": round(median(nets), 2),
        f"net_p{lo}": round(_percentile(nets, lo), 2),
        f"net_p{hi}": round(_percentile(nets, hi), 2),
        "prob_net_positive": round(sum(1 for x in nets if x > 0) / len(nets), 3),
    }


def maker_adjust_net(net_trades, *, spread_saving_usd, fill_rate, seed=7, adverse=False) -> list:
    """Entree MAKER : chaque trade REMPLI economise `spread_saving_usd` (moins de cout), MAIS seule
    une fraction `fill_rate` se remplit. adverse=True => on garde en priorite les PIRES trades
    (selection adverse : les gagnants filent avant que l'ordre passif soit touche) = borne basse
    honnete. adverse=False => drop aleatoire (borne haute). La verite est entre les deux."""
    saving = float(spread_saving_usd)
    xs = [float(t) + saving for t in net_trades]
    fr = min(1.0, max(0.0, float(fill_rate)))
    keep = int(round(len(xs) * fr))
    if keep >= len(xs):
        return xs
    if keep <= 0:
        return []
    if adverse:
        return sorted(xs)[:keep]  # on ne remplit que les moins bons
    rng = random.Random(seed)
    idx = list(range(len(xs)))
    rng.shuffle(idx)
    keep_idx = set(idx[:keep])
    return [xs[i] for i in range(len(xs)) if i in keep_idx]
