"""I3 — MOMENTUM TRANSVERSAL : force relative entre coins (long les forts, short les faibles).

On classe les coins par rendement récent et on va LONG le haut du classement / SHORT le bas, en
gardant l'exposition marché ~neutre (autant de longs que de shorts). Signal PUR ; à valider après
coûts (le momentum crypto est souvent mangé par les frais/slippage). PAPER only.
"""
from __future__ import annotations

from typing import Mapping


def classer(rendements_par_coin: Mapping[str, float]) -> list[tuple[str, float]]:
    """Coins classés par rendement DÉCROISSANT (le plus fort d'abord)."""
    return sorted(((str(c), float(r)) for c, r in (rendements_par_coin or {}).items()),
                  key=lambda kv: -kv[1])


def paniers(rendements_par_coin: Mapping[str, float], *, k: int = 1) -> dict[str, list[str]]:
    """Top-k LONG (forts) / bottom-k SHORT (faibles), delta-neutre au marché. k borné à n//2."""
    classe = classer(rendements_par_coin)
    n = len(classe)
    kk = max(0, min(int(k), n // 2))
    return {"longs": [c for c, _ in classe[:kk]], "shorts": [c for c, _ in classe[n - kk:]]}


__all__ = ["classer", "paniers"]
