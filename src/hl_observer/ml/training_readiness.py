"""D5 — Prêt à entraîner ? Le modèle local ne s'entraîne que sur des issues MIXTES.

Empêche d'entraîner (et donc de sur-ajuster) sur trop peu de trades ou des issues
uniformes. Le modèle filtre, il n'invente jamais de profit. Pur.
"""

from __future__ import annotations


def training_ready(n_wins: int, n_losses: int, *, min_each: int = 20) -> tuple[bool, str]:
    if n_wins < min_each or n_losses < min_each:
        return False, f"INSUFFICIENT_MIXED_OUTCOMES(wins={n_wins},losses={n_losses},min_each={min_each})"
    return True, "READY"


__all__ = ["training_ready"]
