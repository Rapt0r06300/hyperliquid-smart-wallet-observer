"""[ARB pépite 226] COMMON HEDGE QUANTUM : calculer AVANT l'entrée la plus petite taille réellement HEDGEABLE
SIMULTANÉMENT sur les deux venues, après leurs lots respectifs. Si venue A a un lot 0,1 et venue B un lot 0,03, la
plus petite taille couvrable des deux côtés est le PPCM de leurs lots ; entrer en dessous garantit un résidu nu.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _ppcm_decimal(a: Decimal, b: Decimal) -> Decimal:
    """PPCM de deux décimaux positifs via mise à l'échelle entière."""
    scale = 10 ** 9
    ia, ib = int(a * scale), int(b * scale)
    from math import gcd
    return Decimal(ia * ib // gcd(ia, ib)) / scale


def quantum_commun(lot_a: Any, lot_b: Any) -> dict[str, Any]:
    """Plus petite taille multiple des DEUX lots (PPCM). Lot invalide → UNMEASURABLE. Entrer sous ce quantum
    garantit qu'une jambe ne peut pas apparier l'autre exactement (résidu structurel)."""
    if not all(isinstance(x, (int, float)) for x in (lot_a, lot_b)) or lot_a <= 0 or lot_b <= 0:
        return {"quantum": UNMEASURABLE, "raison": "LOT_INVALIDE"}
    q = _ppcm_decimal(Decimal(str(lot_a)), Decimal(str(lot_b)))
    return {"quantum": float(q), "lot_a": float(lot_a), "lot_b": float(lot_b),
            "note": "plus petite taille hedgeable exactement des deux cotes"}


def taille_hedgeable(taille_voulue: Any, *, lot_a: float, lot_b: float) -> dict[str, Any]:
    """Plus grand multiple du quantum commun ≤ taille voulue (0 si sous le quantum). Jamais arrondi vers le haut."""
    qc = quantum_commun(lot_a, lot_b)
    if qc["quantum"] == UNMEASURABLE or not isinstance(taille_voulue, (int, float)):
        return {"taille": UNMEASURABLE, "raison": "NON_MESURABLE"}
    q = qc["quantum"]
    n = int(float(taille_voulue) / q + 1e-12)
    return {"taille": round(n * q, 12), "quantum": q, "residu_evite": bool(n >= 1)}


__all__ = ["quantum_commun", "taille_hedgeable", "UNMEASURABLE"]
