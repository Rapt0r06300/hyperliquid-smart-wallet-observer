"""κ — L'INTENSITÉ DE FILL (idée `kappa_fill` de moisson-fini.md).

*Notre simulateur suppose un fill maker à « 10 % du flux » — **un chiffre INVENTÉ**, jamais
mesuré. Toute conclusion sur le market making en dépend.* Ici on le **mesure** : la probabilité
d'être rempli décroît avec la distance au mid selon λ(δ) = A·e^(−κδ). On ajuste A et κ **par coin**
depuis nos propres L2 + trades (aucun L3 requis).

🔒 **Règles dures (deny-by-default) :**
- **Ne pas savoir n'est pas une permission** : si on n'a pas assez de points distincts, on renvoie
  `None` (→ le noyau doit refuser, pas passer).
- **Un modèle qui ment se refuse** : si l'ajustement donne un fill au mid > 100 % (A > 1), ou une
  intensité qui *augmente* avec la distance (κ ≤ 0), le modèle est FAUX → `None`.
  *Un vrai κ ne peut qu'**abaisser** le fill mesuré à 100 % par T1b (0/29) — donc **confirmer** la
  mort du MM. S'il le ressuscite, c'est le modèle qui ment.*

Module PUR (aucun réseau, aucun état) : il se teste avec des données synthétiques et il alimente
le noyau via `Contexte.kappa` + une porte calquée sur celle du VPIN.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

MIN_POINTS_DISTINCTS = 3      # moins que ça, on ne prétend rien
A_MAX = 1.0                   # le fill au mid (δ=0) ne peut pas dépasser 100 %


@dataclass(frozen=True)
class IntensiteFill:
    """Le résultat d'un ajustement λ(δ) = A·e^(−κδ), pour UN coin."""

    A: float          # fill au mid (δ=0), dans [0, 1]
    kappa: float      # décroissance ; plus c'est grand, plus le fill chute avec la distance
    n: int            # nombre de points utilisés
    r2: float         # qualité de l'ajustement (0..1)

    def proba(self, distance_bps: float) -> float:
        """Probabilité de fill à `distance_bps` du mid, bornée à [0, 1]."""
        p = self.A * math.exp(-self.kappa * max(0.0, float(distance_bps)))
        return max(0.0, min(1.0, p))

    def as_dict(self) -> dict[str, Any]:
        return {"A": self.A, "kappa": self.kappa, "n": self.n, "r2": self.r2}


def estimer(
    observations: Sequence[tuple[float, float]],
    *,
    min_points: int = MIN_POINTS_DISTINCTS,
) -> IntensiteFill | None:
    """Ajuste (A, κ) par régression log-linéaire sur des couples (distance_bps, taux_de_fill).

    `taux_de_fill` ∈ ]0, 1] = fraction des ordres postés à cette distance qui ont été remplis.
    Renvoie `None` si la mesure est impossible ou si le modèle obtenu est invalide (voir en-tête).
    """
    pts = [
        (float(d), float(r))
        for d, r in observations
        if d is not None and r is not None and float(r) > 0.0 and float(d) >= 0.0
    ]
    if len({round(d, 6) for d, _ in pts}) < min_points:
        return None  # pas assez de distances distinctes → on REFUSE

    xs = [d for d, _ in pts]
    ys = [math.log(r) for _, r in pts]        # ln(r) = ln(A) − κ·δ  → droite
    n = len(pts)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0.0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    pente = sxy / sxx          # = −κ
    intercept = my - pente * mx  # = ln(A)
    kappa = -pente
    A = math.exp(intercept)

    # 🔒 garde-fous : un modèle qui donne un fill au mid > 100 % ou qui AUGMENTE avec la distance
    #    est FAUX. On ne branche pas un modèle qui ressusciterait un MM mort.
    if kappa <= 0.0 or A > A_MAX + 1e-9:
        return None

    sst = sum((y - my) ** 2 for y in ys) or 1e-12
    ssr = sum((ys[i] - (intercept + pente * xs[i])) ** 2 for i in range(n))
    r2 = max(0.0, 1.0 - ssr / sst)
    return IntensiteFill(A=min(A, 1.0), kappa=kappa, n=n, r2=r2)
