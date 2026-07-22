"""ROBUSTESSE DE SÉLECTION — rendre la recherche EXTRÊME sans en faire une machine à faux
gagnants (22/07, demande de Flo « trouve tous les meilleurs calibrages, extrême ET robuste »).

LE PIÈGE QUE CE MODULE FERME
----------------------------
Plus on essaie de configurations, plus la MEILLEURE d'entre elles a de chances d'être un
gagnant CHANCEUX — pas un edge. Une recherche à 1 420 essais qui ne pénalise pas le nombre
d'essais est une **fabrique d'artefacts**. La robustesse doit donc GRANDIR avec l'agressivité
de la recherche. Deux outils, tous deux standards de la littérature quant :

1. **PBO — Probability of Backtest Overfitting** (Bailey & López de Prado, 2014), via CSCV
   (Combinatorially-Symmetric Cross-Validation). On découpe la performance en S blocs
   temporels, on forme toutes les partitions IS/OOS de S/2 blocs, et pour chacune : la config
   la MEILLEURE en IS, à quel rang tombe-t-elle en OOS ? Si elle passe SOUS la médiane OOS,
   c'est une instance de sur-ajustement. **PBO = fraction de partitions sur-ajustées.**
   PBO ≈ 0 → la procédure GÉNÉRALISE ; PBO ≥ 0,5 → elle sur-ajuste, le « meilleur » est du bruit.

2. **Le seuil de bruit du multiple-testing** : avec N essais indépendants d'espérance nulle,
   le meilleur atteint déjà ≈ σ·√(2·ln N) par pur hasard. Un gagnant qui ne dépasse pas cette
   barre n'a rien prouvé — il a juste gagné à la loterie des N tirages.

Ce module ne PROMET aucun edge. Il REFUSE d'en déclarer un qui ne survit pas à ces deux tests.
Pur calcul sur une matrice de performances déjà mesurées : aucune donnée réseau, aucun ordre.
"""
from __future__ import annotations

import itertools
import math
import random
import statistics
from typing import Any, Sequence

#: au-dessus, la procédure de sélection sur-ajuste : le « meilleur » ne généralise pas.
PBO_SEUIL = 0.5
#: plafond de partitions IS/OOS évaluées (C(S,S/2) explose ; on échantillonne, graine fixe).
MAX_PARTITIONS = 2000


def _matrice_propre(matrice: Sequence[Sequence[float]]) -> tuple[list[list[float]], int]:
    """Nettoie la matrice [config][bloc] : lignes non vides, S bloc(s) PAIR commun. Rend (M, S)."""
    lignes = []
    for row in matrice or []:
        try:
            vals = [float(x) for x in row]
        except (TypeError, ValueError):
            continue
        if vals:
            lignes.append(vals)
    if len(lignes) < 2:
        return [], 0
    s = min(len(r) for r in lignes)
    s -= s % 2                                   # S doit être pair pour partitionner en 2 moitiés
    if s < 4:
        return [], s
    return [r[:s] for r in lignes], s


def pbo_cscv(matrice: Sequence[Sequence[float]], *, max_partitions: int = MAX_PARTITIONS,
             graine: int = 7) -> dict[str, Any]:
    """PBO par CSCV sur une matrice [config][bloc] de performance (plus haut = mieux).

    Rend {pbo, n_configs, n_blocs, n_partitions, lambda_median, verdict}. `pbo=None` si la
    matrice est trop maigre (< 2 configs ou < 4 blocs pairs) — INSUFFISANT, jamais un faux 0.
    """
    M, S = _matrice_propre(matrice)
    if not M:
        return {"pbo": None, "n_configs": len(matrice or []), "n_blocs": S,
                "verdict": "INSUFFISANT (< 2 configs ou < 4 blocs pairs)", "real_execution": False}
    N = len(M)
    blocs = list(range(S))
    partitions = list(itertools.combinations(blocs, S // 2))
    if len(partitions) > max_partitions:
        partitions = random.Random(graine).sample(partitions, max_partitions)
    n_surajuste = 0
    lambdas: list[float] = []
    for IS in partitions:
        ens_is = set(IS)
        OOS = [b for b in blocs if b not in ens_is]
        perf_is = [sum(M[i][b] for b in IS) for i in range(N)]
        perf_oos = [sum(M[i][b] for b in OOS) for i in range(N)]
        n_star = max(range(N), key=lambda i: perf_is[i])          # la meilleure EN IS
        val = perf_oos[n_star]
        rang = sum(1 for i in range(N) if perf_oos[i] <= val)     # rang OOS de la meilleure IS (1..N)
        omega = min(max(rang / (N + 1), 1e-6), 1 - 1e-6)          # rang relatif dans (0,1)
        lam = math.log(omega / (1 - omega))                       # logit : <0 => sous la médiane OOS
        lambdas.append(lam)
        if lam < 0:
            n_surajuste += 1
    pbo = n_surajuste / len(partitions)
    return {"pbo": round(pbo, 4), "n_configs": N, "n_blocs": S, "n_partitions": len(partitions),
            "lambda_median": round(statistics.median(lambdas), 4),
            "verdict": "SUR_AJUSTE" if pbo > PBO_SEUIL else "ROBUSTE", "real_execution": False}


def seuil_bruit_multiple_testing(n_essais: int, sigma: float) -> float:
    """La performance qu'atteint DÉJÀ le meilleur de `n_essais` tirages d'espérance nulle, par
    pur hasard : σ·√(2·ln N). Un gagnant qui ne la dépasse pas n'a rien prouvé."""
    n = max(int(n_essais or 0), 2)
    return float(sigma) * math.sqrt(2.0 * math.log(n))


def verdict_robustesse(matrice: Sequence[Sequence[float]], n_essais: int, *,
                       net_gagnant: float | None = None, sigma_null: float | None = None,
                       max_partitions: int = MAX_PARTITIONS) -> dict[str, Any]:
    """Le verdict combiné : ROBUSTE seulement si (PBO <= 0,5) ET (le gagnant bat le seuil de
    bruit du multiple-testing, quand on peut le calculer). DENY-BY-DEFAULT : un PBO incalculable
    n'est jamais 'robuste'."""
    res = pbo_cscv(matrice, max_partitions=max_partitions)
    res["n_essais"] = int(n_essais or 0)
    robuste = (res.get("pbo") is not None) and (res["pbo"] <= PBO_SEUIL)
    if net_gagnant is not None and sigma_null:
        seuil = seuil_bruit_multiple_testing(n_essais, sigma_null)
        res["seuil_bruit"] = round(seuil, 6)
        res["bat_le_bruit"] = bool(net_gagnant > seuil)
        robuste = robuste and res["bat_le_bruit"]
    res["robuste"] = bool(robuste)
    if res.get("pbo") is None:
        res["verdict"] = "INSUFFISANT"
    elif not robuste and res.get("verdict") == "ROBUSTE":
        res["verdict"] = "SUR_AJUSTE"          # le PBO passe mais le bruit non -> pas robuste
    return res


__all__ = ["PBO_SEUIL", "MAX_PARTITIONS", "pbo_cscv", "seuil_bruit_multiple_testing",
           "verdict_robustesse"]
