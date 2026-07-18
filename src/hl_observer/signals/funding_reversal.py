"""I6 — FUNDING EXTRÊME → RETOURNEMENT (contrarian). Réutilise le z-score (A4).

Un funding anormalement HAUT = longs surpeuplés → biais de retournement BAISSIER (fade). Anormalement
BAS/négatif = shorts surpeuplés → biais HAUSSIER. C'est un signal DIRECTIONNEL contrarian, distinct
du carry (qui, lui, encaisse le funding). Signal PUR, à valider au markout. PAPER only.
"""
from __future__ import annotations

SEUIL_Z_EXTREME = 2.0        # |z| >= 2 = funding vraiment extreme (surpeuplement)


def signal_reversal(funding_zscore: float, *, seuil_z: float = SEUIL_Z_EXTREME) -> str | None:
    """z >= +seuil -> 'SHORT' (fade les longs surpeuplés) ; z <= -seuil -> 'LONG' ; sinon None."""
    try:
        z = float(funding_zscore)
    except (TypeError, ValueError):
        return None
    if z >= float(seuil_z):
        return "SHORT"
    if z <= -float(seuil_z):
        return "LONG"
    return None


__all__ = ["SEUIL_Z_EXTREME", "signal_reversal"]
