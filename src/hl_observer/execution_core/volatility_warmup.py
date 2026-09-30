"""[CROSS-VENUE lot2 #72] WARM-UP VOLATILITÉ SÉPARÉ : le warm-up de l'estimateur de volatilité est DISTINCT du
warm-up du carnet. Le carnet peut être « prêt » (seedé) alors que la volatilité, elle, a besoin de bien plus
d'observations pour être fiable. Les mélanger ferait trader avec une vol sous-estimée. Buffer dédié, minimum propre.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class WarmupVolatilite:
    """Buffer dédié à la volatilité. `pret` seulement au-delà d'un nombre minimum d'observations de vol."""

    def __init__(self, *, min_observations: int = 100) -> None:
        self.min_observations = int(min_observations)
        self._n = 0

    def observer(self, *, n: int = 1) -> None:
        self._n += int(n)

    def pret(self) -> dict[str, Any]:
        ok = self._n >= self.min_observations
        return {"pret": bool(ok), "n": self._n, "min": self.min_observations,
                "composante": "VOLATILITE", "raison": ("OK" if ok else "WARMUP_VOL_INCOMPLET")}


__all__ = ["WarmupVolatilite"]
