"""[EXEC pépite 205] AMEND-VS-FILL RACE RESOLVER : même résolution CAUSALE lorsqu'un fill appartient à l'ANCIENNE
quantité/prix pendant qu'un AMEND est en vol. Un fill horodaté AVANT l'acceptation de l'amend doit être attribué à la
version d'ordre AVANT amend (ancien prix/qté), pas à la nouvelle. Attribuer le fill à la mauvaise version fausse le
prix moyen et la quantité. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

VERSION_AVANT_AMEND = "VERSION_AVANT_AMEND"
VERSION_APRES_AMEND = "VERSION_APRES_AMEND"
INDETERMINE = "INDETERMINE"


def resoudre(*, fill_seq: Any, amend_accepte_seq: Any) -> dict[str, Any]:
    """Attribue le fill à la version d'ordre selon la causalité. fill_seq < amend_accepte_seq → le fill précède
    l'amend → VERSION_AVANT_AMEND (ancien prix/qté). fill_seq ≥ amend → VERSION_APRES_AMEND. Séquence manquante →
    INDETERMINE (ne pas attribuer au hasard)."""
    if not all(isinstance(x, (int, float)) for x in (fill_seq, amend_accepte_seq)):
        return {"attribution": INDETERMINE, "raison": "SEQUENCE_MANQUANTE"}
    if int(fill_seq) < int(amend_accepte_seq):
        return {"attribution": VERSION_AVANT_AMEND, "raison": "FILL_AVANT_ACCEPTATION_AMEND"}
    return {"attribution": VERSION_APRES_AMEND, "raison": "FILL_APRES_ACCEPTATION_AMEND"}


__all__ = ["resoudre", "VERSION_AVANT_AMEND", "VERSION_APRES_AMEND", "INDETERMINE"]
