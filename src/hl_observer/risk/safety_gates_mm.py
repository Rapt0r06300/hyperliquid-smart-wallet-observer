"""M6 + M7 — KILL-SWITCH divergence de sources & LEVIER conditionnel au RÉGIME.

M6 : comparer les marks de plusieurs sources (HL vs Binance/Coinbase) ; une divergence anormale =
donnée douteuse / résolution suspecte -> SAFE MODE (NO_TRADE). M7 : plafonner le levier selon le
régime (vol haute / expansion -> moins de levier ; calme -> plus). PAPER only.
"""
from __future__ import annotations

from typing import Sequence

SEUIL_DIVERGENCE_FRAC = 0.01     # > 1% d'écart entre sources = suspect

# plafond de levier par régime (I8 / K5)
LEVIER_MAX_PAR_REGIME = {"CONTRACTION": 10.0, "NORMAL": 5.0, "EXPANSION": 2.0}


def divergence_max_frac(marks: Sequence[float]) -> float | None:
    """Écart relatif max entre sources (référence = médiane). None si < 2 sources valides."""
    vals = [float(m) for m in (marks or []) if isinstance(m, (int, float)) and float(m) > 0]
    if len(vals) < 2:
        return None
    vals_tries = sorted(vals)
    ref = vals_tries[len(vals_tries) // 2]           # médiane ; strictement > 0 par construction
    return max(abs(v - ref) / ref for v in vals)


def mode_sur(marks: Sequence[float], *, seuil_frac: float = SEUIL_DIVERGENCE_FRAC) -> bool:
    """True = SÛR (on peut trader). Divergence excessive ou non mesurable -> False (SAFE MODE)."""
    d = divergence_max_frac(marks)
    return d is not None and d <= float(seuil_frac)


def levier_max_regime(regime: str, *, base: float = 5.0) -> float:
    """Plafond de levier selon le régime de vol. Régime inconnu -> `base` (prudent)."""
    return float(LEVIER_MAX_PAR_REGIME.get(str(regime).upper(), base))


__all__ = ["SEUIL_DIVERGENCE_FRAC", "LEVIER_MAX_PAR_REGIME", "divergence_max_frac",
           "mode_sur", "levier_max_regime"]
