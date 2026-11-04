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


def atomic_cursor_fill_receipt(*, fill_id: Any, cursor_before: Any, cursor_after: Any,
                               fill_persisted: Any, cursor_persisted: Any) -> dict[str, Any]:
    """Allow resume only when fill and cursor persistence form one complete commit."""

    valid = (
        isinstance(fill_id, str) and bool(fill_id.strip())
        and type(cursor_before) is int and type(cursor_after) is int
        and cursor_after >= cursor_before
        and type(fill_persisted) is bool and type(cursor_persisted) is bool
    )
    if not valid:
        return {"status": "UNMEASURABLE", "committed": False, "resume_allowed": False, "reason": "ATOMICITY_INPUT_INVALID", "paper_read_only": True}
    committed = fill_persisted and cursor_persisted
    return {"status": "PROVEN", "committed": committed, "resume_allowed": committed,
            "reason": "COMMIT_COMPLETE" if committed else "COMMIT_INCOMPLETE", "paper_read_only": True}


__all__ = ["CurseurStream", "atomic_cursor_fill_receipt"]
