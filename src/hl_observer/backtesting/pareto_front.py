"""AUD-153 — front de PARETO conserve (optimisation multi-objectifs).

Etant donne des points multi-objectifs (a MAXIMISER), on conserve le FRONT DE PARETO : les points
NON DOMINES (aucun autre n'est >= sur tous les objectifs et > sur au moins un). On ne jette pas les
compromis. Read-only.
"""
from __future__ import annotations

from typing import Sequence


def _domine(a, b) -> bool:
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def front_pareto(points: Sequence[dict], *, objectifs: Sequence[str]) -> list:
    """points = [{..., obj1:v, obj2:v}]. Rend le sous-ensemble NON DOMINE (front de Pareto)."""
    vals = [tuple(float(p[o]) for o in objectifs) for p in points]
    front = []
    for i, p in enumerate(points):
        if not any(_domine(vals[j], vals[i]) for j in range(len(points)) if j != i):
            front.append(p)
    return front


__all__ = ["front_pareto"]
