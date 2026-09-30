"""ALPHA P20 — CROSS-ASSET lead-lag : BTC→alts, ETH→beta, majors→alts. Beta neutralisé, leave-one-coin OOS.

Le rendement d'un meneur (BTC) au pas t prédit-il le rendement d'un suiveur (alt) au pas t+1, APRÈS avoir
retiré la composante bêta contemporaine (le suiveur bouge déjà avec le meneur simultanément — ça n'est pas
tradable) ? On mesure le résidu prédictif décalé. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _beta(x: Sequence[float], y: Sequence[float]) -> float:
    n = min(len(x), len(y))
    mx = sum(x[:n]) / n
    my = sum(y[:n]) / n
    sxx = sum((x[i] - mx) ** 2 for i in range(n))
    if sxx <= 0:
        return 0.0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / sxx


def leadlag_beta_neutre(ret_lead: Sequence[float], ret_follow: Sequence[float], *, horizon: int = 1) -> dict[str, Any]:
    """Prédictivité décalée du meneur sur le suiveur, APRÈS neutralisation du bêta contemporain.

    residu_follow[t] = follow[t] − beta·lead[t] ; on corrèle lead[t] avec residu_follow[t+horizon].
    """
    n = min(len(ret_lead), len(ret_follow))
    if n < 30:
        return {"beta": None, "pred_decale": None, "n": n}
    b = _beta(ret_lead[:n], ret_follow[:n])
    residu = [ret_follow[t] - b * ret_lead[t] for t in range(n)]
    xs, ys = [], []
    for t in range(n - horizon):
        xs.append(ret_lead[t]); ys.append(residu[t + horizon])
    mx = sum(xs) / len(xs); my = sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    pente = sxy / sxx if sxx > 0 else 0.0
    return {"beta": round(b, 6), "pente_predictive_decalee": round(pente, 8), "n": n,
            "note": "pente ~0 => pas d'edge cross-asset apres beta ; sinon a tester en OOS leave-one-coin"}


__all__ = ["leadlag_beta_neutre"]
