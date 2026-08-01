"""[DATA lot2 #31] CHECKSUM DU CARNET : lorsqu'une venue expose un checksum de son carnet, on le compare au checksum
CALCULÉ localement. Un mismatch signifie que notre carnet local a divergé (delta manqué/mal appliqué) → le carnet
devient IMMÉDIATEMENT INVALID (on ne trade plus dessus jusqu'au resync). Checksum absent → INVALID (fail-closed).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

VALID = "VALID"
INVALID = "INVALID"


def valider(checksum_local: Any, checksum_venue: Any) -> dict[str, Any]:
    """VALID seulement si les deux checksums existent ET sont égaux. Sinon INVALID (carnet à resync)."""
    if checksum_local is None or checksum_venue is None:
        return {"etat": INVALID, "raison": "CHECKSUM_ABSENT"}
    ok = str(checksum_local) == str(checksum_venue)
    return {"etat": (VALID if ok else INVALID),
            "raison": ("OK" if ok else "CHECKSUM_MISMATCH_CARNET_DIVERGE")}


__all__ = ["valider", "VALID", "INVALID"]
