"""[COPY-VAULT lot2 #65] HEARTBEAT/LIVENESS PAR VAULT : un heartbeat/liveness PROPRE à chaque vault, INDÉPENDANT du
heartbeat général du bot. Le bot peut tourner parfaitement alors qu'UN vault précis ne reçoit plus rien (son flux à
lui est mort). Sans heartbeat par vault, ce silence ciblé passe inaperçu et on copie un leader qu'on ne voit plus.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class HeartbeatVaults:
    """Suit le dernier signe de vie PAR vault. Un vault silencieux depuis plus de timeout est déclaré mort."""

    def __init__(self, *, timeout_ms: float = 30_000.0) -> None:
        self.timeout_ms = float(timeout_ms)
        self._dernier_ms: dict[str, float] = {}

    def battement(self, vault: str, *, now_ms: float) -> None:
        self._dernier_ms[str(vault)] = float(now_ms)

    def vivant(self, vault: str, *, now_ms: Any) -> dict[str, Any]:
        """Vivant si un battement a été reçu depuis ≤ timeout. Jamais vu ou horodatage invalide → mort (prudence)."""
        if not isinstance(now_ms, (int, float)):
            return {"vivant": False, "raison": "TEMPS_INVALIDE"}
        dernier = self._dernier_ms.get(str(vault))
        if dernier is None:
            return {"vivant": False, "raison": "AUCUN_BATTEMENT"}
        silence = float(now_ms) - dernier
        vivant = silence <= self.timeout_ms
        return {"vivant": bool(vivant), "silence_ms": round(silence, 3),
                "raison": ("OK" if vivant else "VAULT_SILENCIEUX")}


__all__ = ["HeartbeatVaults"]
