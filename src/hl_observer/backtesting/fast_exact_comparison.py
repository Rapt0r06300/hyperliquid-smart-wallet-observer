"""AUD-149 — comparaison FAST vs EXACT (le fast-screen doit s'accorder avec le moteur exact).

Le fast-screen (vectorise) filtre vite ; le moteur exact tranche. Ils doivent CONCORDER sur les
configs retenues : une divergence = le fast ment (faux positif/negatif). Ce module compare et liste
les desaccords sur l'intersection des configs. Read-only.
"""
from __future__ import annotations

from typing import Mapping


def comparer_fast_exact(fast: Mapping[str, bool], exact: Mapping[str, bool]) -> dict:
    """fast/exact = {config: retenue?}. Concordent ssi memes decisions sur l'intersection."""
    communs = set(fast) & set(exact)
    faux_positifs = sorted(c for c in communs if fast[c] and not exact[c])
    faux_negatifs = sorted(c for c in communs if not fast[c] and exact[c])
    return {"concordent": not faux_positifs and not faux_negatifs,
            "faux_positifs": faux_positifs, "faux_negatifs": faux_negatifs, "n_communs": len(communs)}


__all__ = ["comparer_fast_exact"]
