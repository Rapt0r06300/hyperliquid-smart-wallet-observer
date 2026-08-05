"""AUD-136 — priorite du capital STRICT : le strict se sert EN PREMIER dans l'enveloppe unique.

L'allocation de l'enveloppe 1000 (cf AUD-122) sert d'abord la voie STRICTE ; l'exploratoire ne
recoit que le RESTE. Le strict n'est JAMAIS affame par l'exploratoire. Read-only, paper.
"""
from __future__ import annotations

from typing import Mapping

ENVELOPPE = 1000.0


def allouer_avec_priorite_strict(demandes: Mapping[str, float], *, strict_key: str = "strict",
                                 enveloppe: float = ENVELOPPE) -> dict:
    """Sert `strict` en premier (borne par l'enveloppe), puis repartit le RESTE entre les autres au
    prorata de leurs demandes."""
    strict_dem = float(demandes.get(strict_key, 0.0))
    strict_alloue = min(strict_dem, float(enveloppe))
    reste = float(enveloppe) - strict_alloue
    autres = {k: float(v) for k, v in demandes.items() if k != strict_key and float(v) > 0}
    total = sum(autres.values())
    alloc = {strict_key: round(strict_alloue, 6)}
    for k, v in autres.items():
        alloc[k] = round(reste * (v / total), 6) if total > 0 else 0.0
    return {"allocation": alloc, "strict_alloue": round(strict_alloue, 6),
            "reste_exploratoire": round(reste, 6),
            "strict_servi_avant_exploratoire": strict_alloue >= min(strict_dem, float(enveloppe)) - 1e-9}


__all__ = ["allouer_avec_priorite_strict", "ENVELOPPE"]
