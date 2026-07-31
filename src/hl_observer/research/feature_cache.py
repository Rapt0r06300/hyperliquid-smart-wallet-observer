"""ALPHA P55 — CACHE de features immuable : perf sans changer le résultat (invariance numérique).

Un même (clé = source_hash + transformation + version) → même feature. On mémorise pour ne pas relire tout le
JSONL par trial. Invariant : le résultat est identique avec ou sans cache. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def cle_feature(source: Any, transformation: str, *, version: str = "v1") -> str:
    """Clé IMMUABLE d'une feature = (source + transformation + version). Même triplet → même feature, toujours."""
    return "%s::%s::%s" % (source, transformation, version)


class FeatureCache:
    """Cache clé→valeur immuable. `get_or_compute` ne recalcule jamais une clé déjà vue ; ré-attribuer une
    valeur DIFFÉRENTE à une clé existante est un non-déterminisme et lève (immutabilité stricte)."""

    def __init__(self) -> None:
        self._c: dict[str, Any] = {}
        self.hits = 0
        self.miss = 0

    def get_or_compute(self, cle: str, fn: Callable[[], Any]) -> Any:
        if cle in self._c:
            self.hits += 1
            return self._c[cle]
        self.miss += 1
        v = fn()
        self._c[cle] = v
        return v

    def poser_immuable(self, cle: str, valeur: Any) -> Any:
        """Écriture unique : re-poser une valeur différente pour une clé déjà vue = violation d'immutabilité."""
        if cle in self._c and self._c[cle] != valeur:
            raise ValueError("feature immuable violée pour %r (valeur divergente)" % cle)
        self._c.setdefault(cle, valeur)
        return self._c[cle]

    def invariance_ok(self, cle: str, fn: Callable[[], Any]) -> bool:
        """Vérifie que recalculer donne la même valeur que le cache (déterminisme)."""
        if cle not in self._c:
            return True
        return self._c[cle] == fn()


__all__ = ["FeatureCache", "cle_feature"]
