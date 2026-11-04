"""[COPY-VAULT lot2 #65] HEARTBEAT/LIVENESS PAR VAULT : un heartbeat/liveness PROPRE à chaque vault, INDÉPENDANT du
heartbeat général du bot. Le bot peut tourner parfaitement alors qu'UN vault précis ne reçoit plus rien (son flux à
lui est mort). Sans heartbeat par vault, ce silence ciblé passe inaperçu et on copie un leader qu'on ne voit plus.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any


class HeartbeatVaults:
    """Suit le dernier signe de vie PAR vault. Un vault silencieux depuis plus de timeout est déclaré mort."""

    def __init__(self, *, timeout_ms: float = 30_000.0) -> None:
        try:
            parsed_timeout = float(timeout_ms)
        except (TypeError, ValueError):
            parsed_timeout = float("nan")
        self.timeout_ms = parsed_timeout
        self._invalid_config = not math.isfinite(parsed_timeout) or parsed_timeout < 0
        self._dernier_ms: dict[str, float] = {}

    def battement(self, vault: str, *, now_ms: float) -> None:
        if self._invalid_config or isinstance(now_ms, bool):
            return
        try:
            parsed_now = float(now_ms)
        except (TypeError, ValueError):
            return
        if math.isfinite(parsed_now):
            self._dernier_ms[str(vault)] = parsed_now

    def vivant(self, vault: str, *, now_ms: Any) -> dict[str, Any]:
        """Vivant si un battement a été reçu depuis ≤ timeout. Jamais vu ou horodatage invalide → mort (prudence)."""
        if self._invalid_config or not isinstance(now_ms, (int, float)) or isinstance(now_ms, bool):
            return {"vivant": False, "raison": "TEMPS_INVALIDE"}
        if not math.isfinite(float(now_ms)):
            return {"vivant": False, "raison": "TEMPS_INVALIDE"}
        dernier = self._dernier_ms.get(str(vault))
        if dernier is None:
            return {"vivant": False, "raison": "AUCUN_BATTEMENT"}
        silence = float(now_ms) - dernier
        if silence < 0:
            return {"vivant": False, "silence_ms": round(silence, 3), "raison": "HORLOGE_DU_FUTUR"}
        vivant = silence <= self.timeout_ms
        return {"vivant": bool(vivant), "silence_ms": round(silence, 3),
                "raison": ("OK" if vivant else "VAULT_SILENCIEUX")}


def classify_connection_liveness(*, heartbeat_seen: Any, data_messages: int, subscription_ack: Any) -> dict[str, Any]:
    """Separate a healthy silent market from a subscription that never delivered data."""

    if type(heartbeat_seen) is not bool or type(subscription_ack) is not bool or type(data_messages) is not int or data_messages < 0:
        return {"status": "UNMEASURABLE", "state": "UNKNOWN", "paper_read_only": True}
    if not subscription_ack:
        state = "SUBSCRIPTION_UNCONFIRMED"
    elif data_messages == 0:
        state = "CONNECTED_NO_DATA"
    else:
        state = "DATA_FLOWING"
    return {"status": "PROVEN", "state": state, "heartbeat_seen": heartbeat_seen,
            "data_messages": data_messages, "paper_read_only": True}


__all__ = ["HeartbeatVaults", "classify_connection_liveness"]
