"""[ARB lot2 #10] DEAD-MAN SWITCH PAPER (cancelAllAfter) : si le moteur/heartbeat DISPARAÎT (crash, gel, réseau),
toutes les intentions encore actives deviennent AUTOMATIQUEMENT annulées après un délai — on ne laisse pas des
ordres orphelins vivre sans supervision. Mécanisme cancelAllAfter (Nautilus l'a ajouté côté BitMEX). Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


class DeadManSwitch:
    """Annule toutes les intentions actives si aucun heartbeat n'est reçu depuis plus de `timeout_ms`."""

    def __init__(self, *, timeout_ms: float = 10_000.0) -> None:
        self.timeout_ms = float(timeout_ms)
        self._dernier_heartbeat_ms: Any = None

    def heartbeat(self, now_ms: float) -> None:
        self._dernier_heartbeat_ms = float(now_ms)

    def etat(self, now_ms: Any) -> dict[str, Any]:
        """Déclenché si aucun heartbeat OU si le dernier date de plus de timeout. Déclenché ⇒ tout est annulé."""
        if not isinstance(now_ms, (int, float)):
            return {"declenche": True, "raison": "TEMPS_INVALIDE"}
        if self._dernier_heartbeat_ms is None:
            return {"declenche": True, "raison": "AUCUN_HEARTBEAT"}
        age = float(now_ms) - self._dernier_heartbeat_ms
        if age > self.timeout_ms:
            return {"declenche": True, "age_heartbeat_ms": round(age, 3), "raison": "HEARTBEAT_PERDU_CANCEL_ALL"}
        return {"declenche": False, "age_heartbeat_ms": round(age, 3)}

    def intentions_actives_apres(self, intentions: list[Any], *, now_ms: Any) -> list[Any]:
        """Renvoie les intentions encore actives : vide si le switch est déclenché (tout annulé)."""
        return [] if self.etat(now_ms)["declenche"] else list(intentions)


__all__ = ["DeadManSwitch"]
