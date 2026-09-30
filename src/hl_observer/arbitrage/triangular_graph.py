"""Triangular arbitrage graph for paper/research detection."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations


@dataclass(frozen=True, slots=True)
class TriangularEdge:
    base: str
    quote: str
    rate: float


@dataclass(frozen=True, slots=True)
class TriangularCycle:
    path: tuple[str, str, str]
    product_rate: float


def build_triangular_cycles(edges: list[TriangularEdge]) -> list[TriangularCycle]:
    rates: dict[tuple[str, str], float] = {}
    assets: set[str] = set()
    for edge in edges:
        if edge.rate <= 0:
            continue
        a = edge.base.upper()
        b = edge.quote.upper()
        assets.update((a, b))
        rates[(a, b)] = float(edge.rate)
        rates[(b, a)] = 1.0 / float(edge.rate)
    cycles: list[TriangularCycle] = []
    for a, b, c in permutations(sorted(assets), 3):
        if len({a, b, c}) != 3:
            continue
        if (a, b) in rates and (b, c) in rates and (c, a) in rates:
            product = rates[(a, b)] * rates[(b, c)] * rates[(c, a)]
            cycles.append(TriangularCycle(path=(a, b, c), product_rate=round(product, 12)))
    # canonicalize duplicate rotations by path string.
    seen: set[tuple[str, str, str]] = set()
    unique: list[TriangularCycle] = []
    for cycle in cycles:
        rotations = [cycle.path[i:] + cycle.path[:i] for i in range(3)]
        key = min(rotations)
        if key in seen:
            continue
        seen.add(key)
        unique.append(cycle)
    return unique


__all__ = ["TriangularCycle", "TriangularEdge", "build_triangular_cycles"]
