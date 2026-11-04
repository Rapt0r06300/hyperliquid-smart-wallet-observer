"""AUD-149 — comparaison FAST vs EXACT (le fast-screen doit s'accorder avec le moteur exact).

Le fast-screen (vectorise) filtre vite ; le moteur exact tranche. Ils doivent CONCORDER sur les
configs retenues : une divergence = le fast ment (faux positif/negatif). Ce module compare et liste
les désaccords et les écarts de couverture. Read-only.
"""
from __future__ import annotations

from typing import Mapping


def comparer_fast_exact(fast: Mapping[str, bool], exact: Mapping[str, bool]) -> dict:
    """Compare deux décisions sans accepter une couverture incomplète.

    Une comparaison est certifiante seulement si FAST et EXACT exposent le même
    domaine de configurations et la même décision pour chaque configuration.
    Toute clé absente ou toute valeur non booléenne est donc un échec fermé.
    """
    if not isinstance(fast, Mapping) or not isinstance(exact, Mapping):
        raise TypeError("fast and exact must be mappings")
    invalid_fast = sorted(k for k, value in fast.items() if not isinstance(value, bool))
    invalid_exact = sorted(k for k, value in exact.items() if not isinstance(value, bool))
    if invalid_fast or invalid_exact:
        raise ValueError("fast and exact decisions must be bool")

    communs = set(fast) & set(exact)
    missing_in_fast = sorted(set(exact) - set(fast))
    missing_in_exact = sorted(set(fast) - set(exact))
    faux_positifs = sorted(c for c in communs if fast[c] and not exact[c])
    faux_negatifs = sorted(c for c in communs if not fast[c] and exact[c])
    couverture_complete = not missing_in_fast and not missing_in_exact
    concordent = couverture_complete and not faux_positifs and not faux_negatifs
    return {
        "concordent": concordent,
        "couverture_complete": couverture_complete,
        "status": "PARITY" if concordent else "MISMATCH",
        "faux_positifs": faux_positifs,
        "faux_negatifs": faux_negatifs,
        "missing_in_fast": missing_in_fast,
        "missing_in_exact": missing_in_exact,
        "n_communs": len(communs),
    }


__all__ = ["comparer_fast_exact"]
