"""[DATA pépite 258] SAME-TIMESTAMP RETENTION : plusieurs événements portant EXACTEMENT le même timestamp
doivent tous survivre au cycle cache → disk → replay. Un store naïf indexé par timestamp écraserait les
doublons et perdrait des fills réels ; ici on conserve une liste ordonnée (ts, ordre d'arrivée) : rien n'est
écrasé. Sérialisation → liste plate reconstructible à l'identique. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class StockHorodatage:
    """Conserve tous les événements, y compris à timestamp identique, dans l'ordre d'arrivée. Le replay trie
    par (timestamp, rang d'arrivée) : stable et sans perte. Sérialisable en liste plate (format disque)."""

    def __init__(self) -> None:
        self._events: list[tuple[Any, int, Any]] = []

    def ajouter(self, ts: Any, evenement: Any) -> dict[str, Any]:
        rang = len(self._events)
        self._events.append((ts, rang, evenement))
        return {"ok": True, "taille": len(self._events)}

    def taille(self) -> int:
        return len(self._events)

    def rejouer(self) -> list[Any]:
        """Ordre stable : par timestamp croissant puis par rang d'arrivée (préserve les ex-aequo)."""
        return [ev for _, _, ev in sorted(self._events, key=lambda t: (t[0], t[1]))]

    def serialiser(self) -> list[dict[str, Any]]:
        return [{"ts": ts, "rang": rang, "ev": ev} for ts, rang, ev in self._events]

    @classmethod
    def depuis_serialise(cls, data: list[dict[str, Any]]) -> "StockHorodatage":
        s = cls()
        s._events = [(d["ts"], int(d["rang"]), d["ev"]) for d in data]
        return s


__all__ = ["StockHorodatage"]
