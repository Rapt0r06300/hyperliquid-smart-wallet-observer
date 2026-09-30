"""S6 — POLITIQUE DE RÉSERVE DE MARGE : jamais all-in.

On garde toujours un tampon de marge libre pour survivre aux pics de vol / appels de marge (jambe
perp du carry). Capital déployable = capital × (1 − réserve). PUR. PAPER only.
"""
from __future__ import annotations

RESERVE_FRAC_DEFAUT = 0.2       # 20% de marge toujours libre, non déployable


def capital_deployable(capital: float, *, reserve_frac: float = RESERVE_FRAC_DEFAUT) -> float:
    r = min(1.0, max(0.0, float(reserve_frac)))
    return max(0.0, float(capital) * (1.0 - r))


def respecte_reserve(marge_utilisee: float, capital: float, *, reserve_frac: float = RESERVE_FRAC_DEFAUT) -> bool:
    """True si la marge utilisée laisse la réserve intacte."""
    return float(marge_utilisee) <= capital_deployable(capital, reserve_frac=reserve_frac) + 1e-9


__all__ = ["RESERVE_FRAC_DEFAUT", "capital_deployable", "respecte_reserve"]
