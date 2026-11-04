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


def queue_cap_receipt(events_by_vault: dict[str, int], *, cap_per_vault: int = 100) -> dict[str, Any]:
    """Report per-vault accepted/dropped backlog instead of silently losing bursts."""
    if isinstance(cap_per_vault, bool) or not isinstance(cap_per_vault, int) or cap_per_vault < 1:
        return {"status": "UNMEASURABLE", "reason": "cap_must_be_positive_integer"}
    if not isinstance(events_by_vault, dict) or any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in events_by_vault.values()):
        return {"status": "UNMEASURABLE", "reason": "event_counts_invalid"}
    accepted: dict[str, int] = {}
    dropped: dict[str, int] = {}
    for vault, count in events_by_vault.items():
        accepted[str(vault)] = min(count, cap_per_vault)
        dropped[str(vault)] = max(0, count - cap_per_vault)
    return {"status": "PROVEN", "cap_per_vault": cap_per_vault, "accepted": accepted,
            "dropped": dropped, "diagnostic_preserved": True}


__all__ = ["LimiteurQueueVault"]
