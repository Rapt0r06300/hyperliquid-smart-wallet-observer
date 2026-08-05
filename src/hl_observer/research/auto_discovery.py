"""[AUD-205..211] Auto-decouverte ENCADREE : generation de features nommees, regression symbolique
bornee, recherche genetique COMPTEE dans le multiple-testing, penalite de complexite (parcimonie),
archive Qualite-Diversite (MAP-Elites) a niches, et QUARANTAINE des hypotheses auto-generees.
Deterministe (seed), stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

import math
import random
from typing import Callable, Mapping, Sequence

QUARANTAINE = "QUARANTINE_GENEREE"


def generer_features(base: Sequence[str], *, avec_ratios: bool = True, lags: Sequence[int] = (1,)) -> list[str]:
    """Genere des features derivees NOMMEES (tracables, jamais executees ici) : carres, lags, ratios."""
    feats: list[str] = []
    for f in base:
        feats.append("%s^2" % f)
        for L in lags:
            feats.append("%s[t-%d]" % (f, L))
    if avec_ratios:
        b = list(base)
        for i in range(len(b)):
            for j in range(len(b)):
                if i != j:
                    feats.append("%s/%s" % (b[i], b[j]))
    return feats


def penalite_complexite(score: float, taille: int, *, lambda_: float = 0.01) -> float:
    """Score penalise par la taille de la formule (parcimonie / rasoir d'Occam)."""
    return float(score) - float(lambda_) * int(taille)


def regression_symbolique(xs: Sequence[float], ys: Sequence[float], *, lambda_: float = 0.0) -> dict:
    """Regression symbolique BORNEE : petit catalogue de transformations de x, ajustement moindres
    carres y=a*g(x)+b, garde la meilleure au R2 penalise par la complexite. Deterministe."""
    candidats = [
        ("x", 1, lambda v: v),
        ("x^2", 2, lambda v: v * v),
        ("sqrt(|x|)", 2, lambda v: math.sqrt(abs(v))),
        ("log(|x|+1)", 3, lambda v: math.log(abs(v) + 1.0)),
        ("1/(|x|+1)", 3, lambda v: 1.0 / (abs(v) + 1.0)),
    ]
    n = len(xs)
    best = None
    for nom, taille, g in candidats:
        gx = [g(x) for x in xs]
        mgx = sum(gx) / n
        my = sum(ys) / n
        var = sum((v - mgx) ** 2 for v in gx)
        if var <= 1e-12:
            continue
        a = sum((gx[i] - mgx) * (ys[i] - my) for i in range(n)) / var
        b = my - a * mgx
        sse = sum((ys[i] - (a * gx[i] + b)) ** 2 for i in range(n))
        sst = sum((y - my) ** 2 for y in ys) or 1e-12
        r2 = 1.0 - sse / sst
        note = penalite_complexite(r2, taille, lambda_=lambda_)
        if best is None or note > best["note"]:
            best = {"forme": nom, "a": a, "b": b, "r2": r2, "taille": taille, "note": note}
    return best or {"forme": None, "r2": None, "note": None}


def recherche_genetique(population: Sequence[float], fitness: Callable[[float], float], *,
                        generations: int = 10, seed: int = 7, registre: list | None = None) -> dict:
    """GA minimal (mutation gaussienne + selection elitiste). Si `registre` est fourni, CHAQUE
    evaluation y est comptee -> la recherche genetique entre dans le budget de multiple-testing."""
    rng = random.Random(seed)
    pop = list(population)

    def eval_(v):
        if registre is not None:
            registre.append(v)
        return float(fitness(v))

    best = max(pop, key=eval_)
    for _ in range(generations):
        enfants = [p + rng.gauss(0.0, 1.0) for p in pop]
        combine = pop + enfants
        combine.sort(key=eval_, reverse=True)
        pop = combine[:len(population)]
        if eval_(pop[0]) > eval_(best):
            best = pop[0]
    return {"meilleur": best, "fitness": float(fitness(best)),
            "evaluations": len(registre) if registre is not None else None}


class ArchiveMapElites:
    """Qualite-Diversite : archive de NICHES (cases de descripteur comportemental). Chaque niche ne
    garde que le MEILLEUR individu -> la diversite est preservee, pas seulement l'optimum global."""

    def __init__(self) -> None:
        self._niches: dict = {}

    def proposer(self, individu, descripteur, performance: float) -> bool:
        cle = tuple(descripteur) if isinstance(descripteur, (list, tuple)) else descripteur
        cur = self._niches.get(cle)
        if cur is None or float(performance) > cur[1]:
            self._niches[cle] = (individu, float(performance))
            return True
        return False

    def niches(self) -> dict:
        return {k: v[0] for k, v in self._niches.items()}

    def couverture(self) -> int:
        return len(self._niches)


def quarantaine_generateur(hypotheses: Sequence[Mapping]) -> list[dict]:
    """Toute hypothese AUTO-GENEREE est QUARANTAINEE : non promouvable tant qu'elle n'a pas passe la
    validation hors-echantillon. Empeche un generateur de s'auto-valider (data-mining)."""
    return [{**dict(h), "statut": QUARANTAINE, "promotion_autorisee": False} for h in hypotheses]
