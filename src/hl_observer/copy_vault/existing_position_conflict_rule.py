"""[COPY-VAULT #82] EXISTING-POSITION CONFLICT RULE : un nouveau vault ne doit pas ÉCRASER silencieusement une
position déjà ouverte sur le même coin par un AUTRE module (autre vault, arb, funding). Le conflit est détecté et
doit être résolu explicitement (refus ou fusion décidée), jamais absorbé sans trace. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class RegistreProprietaires:
    """Associe chaque coin à son module propriétaire. Une prise par un autre module = CONFLIT explicite."""

    def __init__(self) -> None:
        self._proprietaire: dict[str, str] = {}

    def proprietaire(self, coin: str) -> Any:
        return self._proprietaire.get(str(coin).upper())

    def demander(self, coin: str, module: str) -> dict[str, Any]:
        """Le module demande la propriété du coin. Libre ou déjà à lui → OK ; détenu par un autre → CONFLIT
        (pas d'écrasement silencieux)."""
        c = str(coin).upper()
        actuel = self._proprietaire.get(c)
        if actuel is None:
            self._proprietaire[c] = str(module)
            return {"ok": True, "raison": "ATTRIBUE"}
        if actuel == str(module):
            return {"ok": True, "raison": "DEJA_PROPRIETAIRE"}
        return {"ok": False, "proprietaire_actuel": actuel, "raison": "CONFLIT_POSITION_EXISTANTE"}

    def liberer(self, coin: str, module: str) -> bool:
        c = str(coin).upper()
        if self._proprietaire.get(c) == str(module):
            del self._proprietaire[c]
            return True
        return False


__all__ = ["RegistreProprietaires"]
