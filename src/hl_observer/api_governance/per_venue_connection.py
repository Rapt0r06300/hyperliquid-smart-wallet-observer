"""[ALL lot2 #25] UNE INSTANCE CONNEXION/RATE-LIMITER PAR VENUE : une SEULE instance de connexion + rate-limiter par
venue, réutilisée partout. Multiplier les instances FRAGMENTE la limite (chaque instance croit avoir tout le budget)
et peut provoquer un ban (CCXT). Le registre garantit qu'un même nom de venue rend toujours la même instance.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any, Callable


class RegistreConnexions:
    """Singleton par venue. `obtenir` crée l'instance à la première demande puis renvoie TOUJOURS la même."""

    def __init__(self, fabrique: Callable[[str], Any] | None = None) -> None:
        self._fabrique = fabrique or (lambda v: {"venue": v, "id": v})
        self._instances: dict[str, Any] = {}
        self.creations = 0

    def obtenir(self, venue: str) -> Any:
        v = str(venue).upper()
        if v not in self._instances:
            self._instances[v] = self._fabrique(v)
            self.creations += 1
        return self._instances[v]

    def nombre_instances(self, venue: str) -> int:
        """Toujours 0 ou 1 par venue : on ne fragmente jamais."""
        return 1 if str(venue).upper() in self._instances else 0


__all__ = ["RegistreConnexions"]
