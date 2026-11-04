"""[AUD-197/199/200/204] Complements de validation statistique : bootstrap STATIONNAIRE
(Politis-Romano, blocs geometriques), Model Confidence Set (elimination du pire jusqu'a
equivalence), alpha-spending pour l'ARRET OPTIONNEL (anti p-hacking sequentiel), et intervalle
CONFORME split (couverture sans hypothese de loi). Deterministe (seed), stdlib pure, 0 reseau."""
from __future__ import annotations

import math
import random
from typing import Any, Mapping, Sequence


def pbo_all_attempts(
    attempts: Sequence[Mapping[str, Any]],
    *,
    max_partitions: int = 2000,
    seed: int = 7,
) -> dict[str, Any]:
    """Calculate CSCV PBO while preserving the exact count of all attempts.

    Every attempt must provide a unique identifier and a complete sequence of
    net performance values under ``performance_by_block``. Invalid or failed
    attempts remain counted in ``n_attempts_total`` but make PBO unmeasurable;
    they are never silently dropped or replaced with zeros. This is a
    PAPER/read-only analysis of already observed values and cannot promote a
    model.
    """
    rows = list(attempts or [])
    base: dict[str, Any] = {
        "pbo": None,
        "n_attempts_total": len(rows),
        "n_attempts_used": 0,
        "n_blocks": 0,
        "n_partitions": 0,
        "attempt_ids": [],
        "invalid_attempt_ids": [],
        "status": "UNMEASURABLE",
        "verdict": "INSUFFISANT",
        "reason": None,
        "selection_source": "all_attempts",
        "real_execution": False,
    }
    if not rows:
        base["reason"] = "aucune_tentative"
        return base
    try:
        from hl_observer.backtesting.robustesse_selection import pbo_cscv
    except ImportError as exc:  # pragma: no cover - fail closed if wiring is broken
        base["reason"] = f"dependance_pbo_indisponible:{exc}"
        return base

    matrices: list[list[float]] = []
    seen_ids: set[str] = set()
    invalid: list[str] = []
    expected_blocks: int | None = None
    for position, row in enumerate(rows):
        attempt_id = row.get("attempt_id")
        attempt_key = str(attempt_id) if attempt_id is not None else f"<row:{position}>"
        base["attempt_ids"].append(attempt_key)
        values = row.get("performance_by_block")
        valid = True
        if not isinstance(attempt_id, str) or not attempt_id.strip() or attempt_id in seen_ids:
            valid = False
        else:
            seen_ids.add(attempt_id)
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            valid = False
        else:
            try:
                numeric = [float(value) for value in values]
            except (TypeError, ValueError):
                valid = False
            else:
                if not numeric or not all(math.isfinite(value) for value in numeric):
                    valid = False
                elif expected_blocks is None:
                    expected_blocks = len(numeric)
                elif len(numeric) != expected_blocks:
                    valid = False
                if valid:
                    matrices.append(numeric)
        if not valid:
            invalid.append(attempt_key)

    base["invalid_attempt_ids"] = invalid
    base["n_attempts_used"] = len(matrices)
    base["n_blocks"] = expected_blocks or 0
    if invalid:
        base["reason"] = "tentatives_incompletes_ou_invalides"
        return base
    if len(matrices) < 2 or (expected_blocks or 0) < 4 or (expected_blocks or 0) % 2:
        base["reason"] = "matrice_insuffisante_pour_cscv"
        return base
    result = pbo_cscv(matrices, max_partitions=max_partitions, graine=seed)
    base.update(
        pbo=result.get("pbo"),
        n_blocks=int(result.get("n_blocs") or 0),
        n_partitions=int(result.get("n_partitions") or 0),
        status="PROVEN" if result.get("pbo") is not None else "UNMEASURABLE",
        verdict=result.get("verdict", "INSUFFISANT"),
        reason=None if result.get("pbo") is not None else result.get("verdict"),
    )
    return base


def calculer_pbo_toutes_les_tentatives(
    attempts: Sequence[Mapping[str, Any]],
    *,
    max_partitions: int = 2000,
    seed: int = 7,
) -> dict[str, Any]:
    """French alias for the strict ``pbo_all_attempts`` API."""
    return pbo_all_attempts(attempts, max_partitions=max_partitions, seed=seed)


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
