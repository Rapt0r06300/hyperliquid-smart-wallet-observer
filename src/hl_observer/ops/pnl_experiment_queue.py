"""AUD-145 — file d'experiences PnL PRIORISEE (par gain attendu).

Les experiences candidates d'amelioration du PnL sont ordonnancees par gain attendu decroissant
(cf AUD-140) : on execute d'abord celle dont le retour espere est le plus grand. Read-only.
"""
from __future__ import annotations

from typing import Sequence

from hl_observer.ops.expected_gain_ranking import classer_actions


def file_experiences_priorisee(experiences: Sequence[dict]) -> list:
    """Experiences triees par gain attendu decroissant, avec un rang 1..N."""
    return [{**e, "rang": i + 1} for i, e in enumerate(classer_actions(experiences))]


__all__ = ["file_experiences_priorisee"]
