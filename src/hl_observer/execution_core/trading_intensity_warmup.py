"""[CROSS-VENUE lot2 #73] WARM-UP TRADING-INTENSITY SÉPARÉ : le warm-up de l'estimateur d'intensité de trading (les
paramètres A/k d'Avellaneda-Stoikov, calibrés sur la fréquence des trades) a son PROPRE buffer, distinct de la vol
et du carnet. Chaque estimateur a un rythme de convergence différent ; un buffer partagé masquerait qu'un seul est
prêt (inspiré de l'implémentation Avellaneda de Hummingbot). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class WarmupIntensite:
    """Buffer dédié à l'intensité de trading. `pret` seulement au-delà d'un minimum d'échantillons de trades."""

    def __init__(self, *, min_echantillons: int = 200) -> None:
        self.min_echantillons = int(min_echantillons)
        self._n = 0

    def observer(self, *, n: int = 1) -> None:
        self._n += int(n)

    def pret(self) -> dict[str, Any]:
        ok = self._n >= self.min_echantillons
        return {"pret": bool(ok), "n": self._n, "min": self.min_echantillons,
                "composante": "TRADING_INTENSITY", "raison": ("OK" if ok else "WARMUP_INTENSITE_INCOMPLET")}


__all__ = ["WarmupIntensite"]
