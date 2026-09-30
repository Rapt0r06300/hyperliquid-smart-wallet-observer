"""[COPY-VAULT #59] STREAM CURSOR PERSISTENCE : mémoriser jusqu'à quel événement (curseur monotone) le vault a été
traité. Au redémarrage, on reprend APRÈS le dernier événement traité, sans re-jouer ni sauter. Un curseur qui
n'avance jamais en arrière garantit qu'un événement déjà consommé n'est pas re-consommé. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any


class CurseurStream:
    """Curseur monotone. `avancer` n'accepte qu'un seq strictement supérieur ; `deja_traite` protège des rejeux."""

    def __init__(self, *, depart: int = -1) -> None:
        self._dernier = int(depart)

    def dernier_traite(self) -> int:
        return self._dernier

    def deja_traite(self, seq: Any) -> bool:
        """Vrai si seq ≤ dernier traité (donc déjà consommé). Seq invalide → considéré déjà traité (prudence)."""
        if not isinstance(seq, (int, float)):
            return True
        return int(seq) <= self._dernier

    def avancer(self, seq: Any) -> dict[str, Any]:
        """Avance le curseur seulement si seq > dernier. Un seq ≤ dernier est refusé (rejeu)."""
        if not isinstance(seq, (int, float)):
            return {"avance": False, "dernier": self._dernier, "raison": "SEQ_INVALIDE"}
        if int(seq) <= self._dernier:
            return {"avance": False, "dernier": self._dernier, "raison": "REJEU_OU_RETARD"}
        self._dernier = int(seq)
        return {"avance": True, "dernier": self._dernier, "raison": "OK"}


__all__ = ["CurseurStream"]
