"""Modele predictif d'edge — ETAPE 5 du plan (le seul vrai front). Régression logistique FROM SCRATCH
(zero dependance). Predit si un signal donnera un trade net-positif, a partir de ses features de scan.

Discipline BLINDEE : standardisation apprise sur le TRAIN uniquement, jugement sur le TEST, et
comparaison a une SELECTION ALEATOIRE (le controle). Attente honnete : marche efficient => probable
echec ; mais si le modele bat le hasard en OOS, on tient enfin un vrai fil. Pur, deterministe.
"""
from __future__ import annotations

import math

FEATURES = ("edge_remaining_bps", "signal_age_ms", "liquidity_score", "consensus_wallets",
            "leader_score", "copy_degradation_bps", "leader_notional_usdt")


def features_of(c) -> list:
    # ROBUSTESSE (fuzzing 2026-07-11) : une entree qui n'est pas un dict ne doit pas faire
    # planter le bot -> vecteur neutre (regle : donnee manquante = etat vide honnete).
    if not isinstance(c, dict):
        return [0.0] * len(FEATURES)
    out = []
    for k in FEATURES:
        v = c.get(k)
        try:
            out.append(float(v) if v is not None else 0.0)
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def fit_standardizer(X):
    # ROBUSTESSE (fuzzing 2026-07-11) : X vide levait IndexError. On rend un standardiseur
    # neutre plutot que de faire tomber la boucle.
    if not X or not X[0]:
        return {"mean": [], "std": []}
    n = len(X); d = len(X[0])
    mean = [0.0] * d
    for row in X:
        for j in range(d):
            mean[j] += row[j]
    mean = [m / n for m in mean]
    var = [0.0] * d
    for row in X:
        for j in range(d):
            var[j] += (row[j] - mean[j]) ** 2
    std = [math.sqrt(v / n) for v in var]
    std = [s if s > 1e-9 else 1.0 for s in std]
    return mean, std


def apply_standardizer(X, mean, std):
    d = len(mean)
    return [[(row[j] - mean[j]) / std[j] for j in range(d)] for row in X]


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def fit_logreg(X, y, *, epochs=150, lr=0.2, l2=1e-4):
    """Descente de gradient full-batch, deterministe (poids initiaux a 0).

    ROBUSTESSE (fuzzing 2026-07-11) : X vide levait IndexError -> modele vide honnete.
    """
    if not X or not X[0]:
        return {"w": [], "b": 0.0}
    n = len(X); d = len(X[0])
    w = [0.0] * d; b = 0.0
    for _ in range(int(epochs)):
        gw = [0.0] * d; gb = 0.0
        for i in range(n):
            p = _sigmoid(b + sum(w[j] * X[i][j] for j in range(d)))
            err = p - y[i]
            for j in range(d):
                gw[j] += err * X[i][j]
            gb += err
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * (gb / n)
    return w, b


def predict_proba(X, w, b):
    return [_sigmoid(b + sum(w[j] * row[j] for j in range(len(row)))) for row in X]
