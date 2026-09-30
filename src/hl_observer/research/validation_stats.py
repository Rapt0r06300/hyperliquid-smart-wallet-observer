"""[AUD-197/199/200/204] Complements de validation statistique : bootstrap STATIONNAIRE
(Politis-Romano, blocs geometriques), Model Confidence Set (elimination du pire jusqu'a
equivalence), alpha-spending pour l'ARRET OPTIONNEL (anti p-hacking sequentiel), et intervalle
CONFORME split (couverture sans hypothese de loi). Deterministe (seed), stdlib pure, 0 reseau."""
from __future__ import annotations

import math
import random
from typing import Mapping, Sequence


def stationary_bootstrap(x: Sequence[float], *, p: float = 0.1, n: int = 1000, seed: int = 7) -> list[list[float]]:
    """Bootstrap STATIONNAIRE : blocs de longueur geometrique (moyenne 1/p), depart aleatoire,
    indices circulaires -> conserve la dependance serielle (contrairement au bootstrap IID)."""
    m = len(x)
    if m == 0:
        return []
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        ech: list = []
        while len(ech) < m:
            i = rng.randrange(m)
            while True:
                ech.append(x[i])
                if len(ech) >= m or rng.random() < p:
                    break
                i = (i + 1) % m
        out.append(ech[:m])
    return out


def model_confidence_set(pertes_par_modele: Mapping[str, Sequence[float]], *, alpha: float = 0.1) -> dict:
    """Model Confidence Set (version deterministe simplifiee) : elimine iterativement le PIRE modele
    tant que l'ecart pire-meilleur depasse un seuil relatif, jusqu'a un ensemble d'EQUIVALENCE."""
    noms = list(pertes_par_modele.keys())
    if not noms:
        return {"mcs": [], "elimines": [], "meilleur": None}
    moy = {k: (sum(v) / len(v) if v else float("inf")) for k, v in pertes_par_modele.items()}
    survivants = list(noms)
    elimines: list = []
    while len(survivants) > 1:
        worst = max(survivants, key=lambda k: moy[k])
        pertes = [moy[k] for k in survivants]
        etendue = max(pertes) - min(pertes)
        moyenne = sum(pertes) / len(pertes)
        if moyenne <= 0 or etendue <= alpha * abs(moyenne):
            break
        survivants.remove(worst)
        elimines.append(worst)
    return {"mcs": sorted(survivants, key=lambda k: moy[k]), "elimines": elimines,
            "meilleur": min(noms, key=lambda k: moy[k])}


def alpha_spending(n_looks: int, *, alpha: float = 0.05, methode: str = "pocock") -> list[float]:
    """Bornes d'ARRET OPTIONNEL : depense le budget d'erreur alpha sur n_looks regards (la somme
    des seuils vaut alpha) -> empeche 'regarder N fois et s'arreter quand c'est significatif'."""
    if n_looks < 1:
        return []
    if methode in ("bonferroni", "pocock"):
        return [alpha / n_looks] * n_looks
    if methode == "obrien":
        poids = [1.0 / ((k / n_looks) ** 0.5) for k in range(1, n_looks + 1)]
        s = sum(poids)
        return [alpha * w / s for w in poids]
    raise ValueError("methode inconnue: %s" % methode)


def intervalle_conforme(residus_calibration: Sequence[float], *, alpha: float = 0.1) -> dict:
    """Prediction CONFORME split : le quantile (1-alpha) des |residus| de calibration donne une
    demi-largeur a couverture marginale >= 1-alpha, SANS hypothese de distribution."""
    r = sorted(abs(e) for e in residus_calibration)
    if not r:
        return {"demi_largeur": None, "couverture_cible": 1 - alpha, "n_calibration": 0}
    n = len(r)
    k = min(n, max(1, math.ceil((n + 1) * (1 - alpha))))
    return {"demi_largeur": r[k - 1], "couverture_cible": 1 - alpha, "n_calibration": n}
