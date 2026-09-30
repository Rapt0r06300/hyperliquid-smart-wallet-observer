"""[COPY-VAULT lot2 #60] SESSION/REBOOTSTRAP MARKERS DANS LE LEDGER : marquer dans le ledger les débuts de session
et les rebootstraps, de sorte qu'on sache PRÉCISÉMENT quelles observations appartiennent à un état source COHÉRENT.
Une observation d'avant un rebootstrap ne doit pas être mélangée avec celles d'après (l'état a été rechargé).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class MarqueursLedger:
    """Attribue chaque observation (par seq) à une SESSION délimitée par les marqueurs session/rebootstrap."""

    def __init__(self) -> None:
        self._marqueurs: list[tuple[int, str]] = []      # (seq_debut, type)
        self._session_courante = 0

    def marquer(self, *, seq: int, type_marqueur: str = "SESSION") -> dict[str, Any]:
        """Ouvre une nouvelle session à partir de `seq` (SESSION ou REBOOTSTRAP)."""
        self._session_courante += 1
        self._marqueurs.append((int(seq), str(type_marqueur).upper()))
        return {"session": self._session_courante, "seq_debut": int(seq), "type": str(type_marqueur).upper()}

    def session_de(self, seq: Any) -> dict[str, Any]:
        """Renvoie l'index de session auquel appartient l'observation `seq` (la dernière ouverte à seq ≤ obs).
        Avant tout marqueur → session 0 (non cohérente, à ne pas fusionner)."""
        if not isinstance(seq, (int, float)):
            return {"session": None, "raison": "SEQ_INVALIDE"}
        idx = 0
        for i, (s, _t) in enumerate(self._marqueurs, start=1):
            if int(seq) >= s:
                idx = i
            else:
                break
        return {"session": idx, "coherente": bool(idx > 0)}


__all__ = ["MarqueursLedger"]
