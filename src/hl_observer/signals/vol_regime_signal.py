"""I8 — RÉGIME DE VOLATILITÉ : expansion vs contraction.

On compare la vol réalisée COURTE à la vol LONGUE : courte >> longue = EXPANSION (post-move, la vol
explose) ; courte << longue = CONTRACTION (compression, pré-breakout possible) ; sinon NORMAL. Sert
à CONDITIONNER la stratégie (carry en calme, momentum en expansion), pas à trader seul. PAPER only.
"""
from __future__ import annotations

from typing import Sequence

RATIO_EXPANSION = 1.5        # vol_courte >= 1.5 x vol_longue -> expansion
RATIO_CONTRACTION = 0.67     # vol_courte <= 0.67 x vol_longue -> contraction


def vol_realisee(rendements: Sequence[float]) -> float | None:
    """Écart-type des rendements. None si < 2 points."""
    xs = [float(x) for x in (rendements or []) if isinstance(x, (int, float))]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def regime_vol(vol_courte: float, vol_longue: float, *, ratio_expansion: float = RATIO_EXPANSION,
               ratio_contraction: float = RATIO_CONTRACTION) -> str | None:
    """EXPANSION / CONTRACTION / NORMAL. None si vol longue invalide."""
    try:
        vc, vl = float(vol_courte), float(vol_longue)
    except (TypeError, ValueError):
        return None
    if vl <= 0:
        return None
    r = vc / vl
    if r >= float(ratio_expansion):
        return "EXPANSION"
    if r <= float(ratio_contraction):
        return "CONTRACTION"
    return "NORMAL"


__all__ = ["RATIO_EXPANSION", "RATIO_CONTRACTION", "vol_realisee", "regime_vol"]
