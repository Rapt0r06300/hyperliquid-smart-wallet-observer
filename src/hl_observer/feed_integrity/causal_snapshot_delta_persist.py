"""[DATA lot2 #69] PERSISTER snapshot→deltas EN ORDRE CAUSAL EXACT : persister un snapshot PUIS ses deltas dans
l'ordre CAUSAL exact où ils sont arrivés, SANS réordonner artificiellement à l'écriture. Réordonner (ex. par
timestamp exchange) casserait la causalité : un delta doit s'appliquer après le snapshot/delta dont il dépend, dans
l'ordre de réception. On refuse toute écriture hors ordre causal. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

SNAPSHOT = "SNAPSHOT"
DELTA = "DELTA"


class PersistanceCausale:
    """Journal snapshot→deltas préservant l'ordre causal (seq strictement croissant). Écriture hors ordre refusée."""

    def __init__(self) -> None:
        self._entrees: list[dict[str, Any]] = []
        self._dernier_seq = -1
        self._a_snapshot = False

    def ajouter(self, *, type_entree: str, seq: Any, payload: Any = None) -> dict[str, Any]:
        """Ajoute une entrée. Le seq doit être strictement > au dernier (ordre causal). Un DELTA avant tout
        SNAPSHOT est refusé (rien à quoi l'appliquer)."""
        if isinstance(seq, bool) or not isinstance(seq, (int, float)) or not math.isfinite(float(seq)):
            return {"ok": False, "raison": "SEQ_INVALIDE"}
        if int(seq) != seq or int(seq) < 0:
            return {"ok": False, "raison": "SEQ_INVALIDE"}
        t = str(type_entree).upper()
        if t not in {SNAPSHOT, DELTA}:
            return {"ok": False, "raison": "TYPE_INVALIDE"}
        if int(seq) <= self._dernier_seq:
            return {"ok": False, "raison": "ECRITURE_HORS_ORDRE_CAUSAL", "dernier_seq": self._dernier_seq}
        if t == DELTA and not self._a_snapshot:
            return {"ok": False, "raison": "DELTA_SANS_SNAPSHOT_PREALABLE"}
        if isinstance(payload, Mapping):
            exchange = payload.get("exchange_ts_ms")
            receive = payload.get("recv_wall_ts_ms", payload.get("received_ts_ms"))
            if exchange is not None and receive is not None:
                try:
                    if int(exchange) > int(receive):
                        return {"ok": False, "raison": "EVENT_AFTER_RECEIVE"}
                except (TypeError, ValueError, OverflowError):
                    return {"ok": False, "raison": "HORLOGE_INVALIDE"}
        if t == SNAPSHOT:
            self._a_snapshot = True
        self._entrees.append({"type": t, "seq": int(seq), "payload": payload})
        self._dernier_seq = int(seq)
        return {"ok": True, "seq": int(seq), "type": t}

    def ordre(self) -> list[int]:
        return [e["seq"] for e in self._entrees]


__all__ = ["PersistanceCausale", "SNAPSHOT", "DELTA"]
