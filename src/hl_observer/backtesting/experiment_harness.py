"""Harnais d'expérience standard (IMPROVE-13) + contrôle aléatoire (IMPROVE-11) + gate 'edge réel'
(IMPROVE-12). Toute nouvelle idée passe par là : entraîner sur le train, sélectionner en OOS,
comparer au HASARD, et n'être promue que si elle passe un critère décidé À L'AVANCE. Aucun ordre.
"""
from __future__ import annotations

import random
from statistics import median

from hl_observer.backtesting import edge_predictor as ep
from hl_observer.backtesting.quant_methods import block_bootstrap


def run_experiment(x_train, y_train, x_test, nets_test, *, seed: int = 0, epochs: int = 120,
                   n_random: int = 30) -> dict:
    """Entraîne un logreg sur (x_train,y_train), sélectionne les trades prédits gagnants du test,
    et compare le net de cette sélection au net de sélections ALÉATOIRES de même taille."""
    mean, std = ep.fit_standardizer(x_train)
    w, b = ep.fit_logreg(ep.apply_standardizer(x_train, mean, std), y_train, epochs=epochs)
    prob = ep.predict_proba(ep.apply_standardizer(x_test, mean, std), w, b)
    sel_idx = [i for i in range(len(nets_test)) if prob[i] > 0.5]
    k = len(sel_idx)
    model_net = sum(nets_test[i] for i in sel_idx)
    rnd = []
    if 0 < k < len(nets_test):
        for s in range(int(n_random)):
            g = random.Random(seed + s)
            pick = g.sample(range(len(nets_test)), k)
            rnd.append(sum(nets_test[i] for i in pick))
    return {
        "selected": k,
        "model_net": round(model_net, 2),
        "random_net_median": round(median(rnd), 2) if rnd else 0.0,
        "random_net_max": round(max(rnd), 2) if rnd else 0.0,
        "beats_random": bool(rnd and model_net > max(rnd)),
    }


def mc_p5(nets, *, block: int = 10, n: int = 2000, seed: int = 7) -> float:
    """5e percentile du net total par bootstrap par blocs (borne basse honnête)."""
    dist = block_bootstrap(nets, block=block, n=n, seed=seed)
    if not dist:
        return 0.0
    dist.sort()
    return dist[max(0, int(0.05 * len(dist)))]


def promotion_gate(net_oos: float, trades: int, *, beats_random: bool, mc_p5_value: float,
                   min_trades: int = 30) -> dict:
    """Critère 'edge réel' FIXÉ À L'AVANCE : net>0 OOS ET bat le hasard ET p5 Monte-Carlo>0 ET
    assez de trades. Sans ce garde-fou, on finit toujours par couronner un mirage."""
    reasons = []
    if net_oos <= 0:
        reasons.append("NET_OOS_NOT_POSITIVE")
    if not beats_random:
        reasons.append("DOES_NOT_BEAT_RANDOM")
    if mc_p5_value <= 0:
        reasons.append("MC_P5_NOT_POSITIVE")
    if (trades or 0) < min_trades:
        reasons.append("TOO_FEW_TRADES")
    return {"promote": len(reasons) == 0, "reasons": reasons}
