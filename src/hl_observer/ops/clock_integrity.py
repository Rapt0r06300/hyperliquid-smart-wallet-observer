"""S1 — INTÉGRITÉ TEMPORELLE : décalage d'horloge + ordering monotone.

En microstructure, un mauvais ordre de ticks fabrique de faux edges. On détecte le SKEW (décalage
horloge locale vs serveur HL) et on REFUSE les events hors-ordre (ts < dernier vu). Deny-by-default.
PAPER only.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_SKEW_MS = 2000.0        # > 2 s de décalage horloge = suspect


def skew_excessif(ts_local_ms: float, ts_serveur_ms: float, *, max_skew_ms: float = MAX_SKEW_MS) -> bool:
    """True si l'horloge locale diverge trop du serveur (données à horodatage douteux)."""
    try:
        return abs(float(ts_local_ms) - float(ts_serveur_ms)) > float(max_skew_ms)
    except (TypeError, ValueError):
        return True


@dataclass(slots=True)
class GardeMonotone:
    """Rejette tout event dont le timestamp recule (hors-ordre) -> ordering garanti."""
    _dernier_ms: int = -1

    def accepter(self, ts_ms: int) -> bool:
        t = int(ts_ms)
        if t < self._dernier_ms:
            return False                              # hors-ordre -> rejeté
        self._dernier_ms = t
        return True


__all__ = ["MAX_SKEW_MS", "skew_excessif", "GardeMonotone"]
