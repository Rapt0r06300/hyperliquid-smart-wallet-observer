"""[AUD-175/177/212] Plans d'experiences : plan factoriel complet, suite basse-discrepance
(Halton, quasi-Monte-Carlo, space-filling, alternative deterministe a Sobol), successive halving
multi-fidelite, et classement par gain d'information. Deterministe, stdlib pure, 0 reseau."""
from __future__ import annotations

from itertools import product
from typing import Callable, Mapping, Sequence

_PREMIERS = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


def plan_factoriel(niveaux_par_facteur: Mapping[str, Sequence]) -> list[dict]:
    """Plan factoriel COMPLET : produit cartesien de tous les niveaux (ordre stable, deterministe)."""
    noms = list(niveaux_par_facteur.keys())
    combos = product(*(list(niveaux_par_facteur[n]) for n in noms))
    return [dict(zip(noms, c)) for c in combos]


def _halton(index: int, base: int) -> float:
    f, r, i = 1.0, 0.0, index
    while i > 0:
        f /= base
        r += f * (i % base)
        i //= base
    return r


def suite_basse_discrepance(dim: int, n: int, *, debut: int = 1) -> list[tuple]:
    """Suite de Halton en dimension `dim` (quasi-MC space-filling). Remplit [0,1)^dim bien plus
    uniformement qu'un tirage pseudo-aleatoire -> meilleure couverture d'espace a budget egal."""
    if dim < 1 or dim > len(_PREMIERS):
        raise ValueError("dim doit etre entre 1 et %d" % len(_PREMIERS))
    return [tuple(_halton(debut + k, _PREMIERS[d]) for d in range(dim)) for k in range(n)]


def successive_halving(configs: Sequence, evaluer: Callable[[object, int], float], *,
                       budget_init: int = 1, facteur: int = 2, budget_max: int | None = None) -> list:
    """Multi-fidelite : evalue toutes les configs a petit budget, garde le meilleur 1/facteur,
    multiplie le budget par `facteur`, recommence. Rend les survivants (meilleur d'abord)."""
    if facteur < 2:
        raise ValueError("facteur >= 2")
    survivants = list(configs)
    budget = max(1, int(budget_init))
    while len(survivants) > 1:
        notes = [(c, float(evaluer(c, budget))) for c in survivants]
        notes.sort(key=lambda t: t[1], reverse=True)
        garde = max(1, len(notes) // facteur)
        survivants = [c for c, _ in notes[:garde]]
        if budget_max is not None and budget >= budget_max:
            break
        budget *= facteur
    return survivants


def classer_par_information_gain(candidats: Sequence[Mapping]) -> list[dict]:
    """Ordonne les candidats par GAIN D'INFORMATION attendu decroissant : tester d'abord ce qui
    reduit le plus l'incertitude. Proxy = incertitude/variance fournie."""
    enrichis = []
    for i, c in enumerate(candidats):
        incert = float(c.get("incertitude", c.get("variance", 0.0)))
        enrichis.append({**dict(c), "rang": 0, "information_gain": incert, "_i": i})
    enrichis.sort(key=lambda d: (-d["information_gain"], d["_i"]))
    for r, d in enumerate(enrichis, 1):
        d["rang"] = r
        d.pop("_i", None)
    return enrichis
