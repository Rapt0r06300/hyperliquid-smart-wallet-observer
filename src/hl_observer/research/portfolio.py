"""ALPHA P49 — PORTEFEUILLE d'alphas : allouer entre edges réellement INDÉPENDANTS.

Quand plusieurs signaux survivent, on ne les additionne pas naïvement : deux alphas peuvent être peu corrélés
en PnL mais trader les MÊMES entités aux MÊMES instants avec le MÊME bêta de marché — donc redondants. On mesure
donc covariance, chevauchement temporel, bêta au facteur commun et chevauchement d'entités, et on alloue plus
aux alphas décorrélés/indépendants ET positifs. Portefeuille pertinent seulement si ≥2 alphas survivent.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 5:
        return None
    ma = sum(a[:n]) / n; mb = sum(b[:n]) / n
    sa = sum((a[i] - ma) ** 2 for i in range(n))
    sb = sum((b[i] - mb) ** 2 for i in range(n))
    if sa <= 0 or sb <= 0:
        return None
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (sa ** 0.5 * sb ** 0.5)


def covariance(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Covariance d'échantillon des PnL alignés (None si < 5 points communs)."""
    n = min(len(a), len(b))
    if n < 5:
        return None
    ma = sum(a[:n]) / n; mb = sum(b[:n]) / n
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (n - 1)


def beta(pnl: Sequence[float], facteur: Sequence[float]) -> float | None:
    """Bêta de l'alpha au facteur commun (marché) = cov(pnl, facteur) / var(facteur). None si non mesurable."""
    n = min(len(pnl), len(facteur))
    if n < 5:
        return None
    mf = sum(facteur[:n]) / n
    vf = sum((facteur[i] - mf) ** 2 for i in range(n)) / (n - 1)
    if vf <= 0:
        return None
    cov = covariance(pnl, facteur)
    return None if cov is None else cov / vf


def _buckets(ts: Iterable[Any], fenetre_ms: float) -> set[int]:
    return {int(float(t) // fenetre_ms) for t in ts if isinstance(t, (int, float)) and not isinstance(t, bool)}


def _jaccard(a: set[Any], b: set[Any]) -> float:
    if not a or not b:
        return 0.0
    u = len(a | b)
    return (len(a & b) / u) if u else 0.0


def chevauchement_temporel(ts_a: Iterable[Any], ts_b: Iterable[Any], *, fenetre_ms: float = 1000.0) -> float:
    """Jaccard des fenêtres temporelles actives : deux alphas actifs aux mêmes instants sont redondants."""
    return _jaccard(_buckets(ts_a, fenetre_ms), _buckets(ts_b, fenetre_ms))


def chevauchement_entites(ent_a: Iterable[Any], ent_b: Iterable[Any]) -> float:
    """Jaccard des entités (coins / wallets) : deux alphas sur les mêmes entités partagent le même risque."""
    return _jaccard(set(ent_a), set(ent_b))


def _overlap_beta(bk: float | None, bj: float | None) -> float:
    """Exposition partagée au facteur : même signe de bêta -> risque commun (ratio des magnitudes)."""
    if bk is None or bj is None or bk == 0 or bj == 0 or (bk > 0) != (bj > 0):
        return 0.0
    return min(abs(bk), abs(bj)) / max(abs(bk), abs(bj))


def allocation(pnl_par_alpha: Mapping[str, Sequence[float]], *,
               horodatages: Mapping[str, Sequence[Any]] | None = None,
               entites: Mapping[str, Iterable[Any]] | None = None,
               facteur: Sequence[float] | None = None, fenetre_ms: float = 1000.0) -> dict[str, Any]:
    """Poids ∝ (edge moyen positif) / (1 + redondance), où redondance = Σ_{autres} [ corr⁺ + overlap_temporel
    + overlap_entités + overlap_bêta ] (chaque terme n'entre que si sa donnée est fournie). Normalisé à 1.
    Portefeuille pertinent seulement si ≥2 alphas positifs survivent (sinon SOLO / aucun)."""
    alphas = {k: [float(x) for x in v] for k, v in pnl_par_alpha.items() if len(v) >= 5}
    if not alphas:
        return {"poids": {}, "verdict": "MORE_DATA"}
    edges = {k: statistics.mean(v) for k, v in alphas.items()}
    positifs = [k for k in alphas if edges[k] > 0]
    betas = ({k: beta(v, facteur) for k, v in alphas.items()} if facteur is not None else {})
    brut: dict[str, float] = {}
    for k, v in alphas.items():
        if edges[k] <= 0:
            brut[k] = 0.0
            continue
        redondance = 0.0
        for j, w in alphas.items():
            if j == k:
                continue
            c = correlation(v, w)
            redondance += max(0.0, c) if c is not None else 0.0
            if horodatages is not None:
                redondance += chevauchement_temporel(horodatages.get(k, []), horodatages.get(j, []),
                                                      fenetre_ms=fenetre_ms)
            if entites is not None:
                redondance += chevauchement_entites(entites.get(k, []), entites.get(j, []))
            if facteur is not None:
                redondance += _overlap_beta(betas.get(k), betas.get(j))
        brut[k] = edges[k] / (1.0 + redondance)
    total = sum(brut.values())
    poids = {k: round(v / total, 4) for k, v in brut.items()} if total > 0 else {k: 0.0 for k in brut}
    if total <= 0:
        verdict = "AUCUN_ALPHA_POSITIF"
    elif len(positifs) == 1:
        verdict = "SOLO"                          # un seul survivant : portefeuille non pertinent (poids trivial)
    else:
        verdict = "ALLOUE"
    out = {"poids": poids, "edges_moyens": {k: round(v, 4) for k, v in edges.items()},
           "n_positifs": len(positifs), "verdict": verdict}
    if facteur is not None:
        out["betas"] = {k: (round(b, 4) if isinstance(b, (int, float)) else None) for k, b in betas.items()}
    return out


__all__ = ["correlation", "covariance", "beta", "chevauchement_temporel", "chevauchement_entites", "allocation"]
