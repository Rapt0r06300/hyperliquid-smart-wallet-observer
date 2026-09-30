"""[COPY-VAULT lot2 #47] QUEUE-CAP PAR VAULT : un vault hyperactif ne doit pas pouvoir faire patienter les
événements des AUTRES leaders en saturant la file commune. Chaque vault a un plafond de file propre ; au-delà, ses
nouveaux événements sont refusés (ou droppés) sans bloquer les autres. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class LimiteurQueueVault:
    """Plafonne la profondeur de file PAR vault. Un vault plein ne peut pas empiéter sur les autres."""

    def __init__(self, *, cap_par_vault: int = 100) -> None:
        self.cap = int(cap_par_vault)
        self._profondeur: dict[str, int] = {}

    def peut_ajouter(self, vault: str) -> dict[str, Any]:
        n = self._profondeur.get(str(vault), 0)
        ok = n < self.cap
        return {"ok": bool(ok), "profondeur": n, "cap": self.cap,
                "raison": ("OK" if ok else "QUEUE_VAULT_PLEINE")}

    def ajouter(self, vault: str) -> bool:
        if not self.peut_ajouter(vault)["ok"]:
            return False
        self._profondeur[str(vault)] = self._profondeur.get(str(vault), 0) + 1
        return True

    def retirer(self, vault: str) -> None:
        self._profondeur[str(vault)] = max(0, self._profondeur.get(str(vault), 0) - 1)


__all__ = ["LimiteurQueueVault"]
