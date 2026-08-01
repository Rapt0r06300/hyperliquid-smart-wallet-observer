"""[EXEC pépite 208] WORKING-ORDER RECONCILIATION : comparer nos ordres locaux ACTIFS aux ordres RÉELLEMENT actifs
d'après la source autoritaire ; toute divergence doit être CLASSIFIÉE (pas juste détectée). Un ordre local actif
absent de la source = fantôme (à nettoyer) ; un ordre actif à la source absent en local = orphelin (à adopter/annuler).
On classe chaque divergence pour savoir quoi en faire. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def reconcilier(locaux_actifs: Iterable[Any], source_actifs: Iterable[Any]) -> dict[str, Any]:
    """Classe les divergences : LOCAL_SEULEMENT (fantôme, actif chez nous mais pas à la source),
    SOURCE_SEULEMENT (orphelin, actif à la source mais pas chez nous), APPARIES (cohérents)."""
    loc = set(str(x) for x in locaux_actifs)
    src = set(str(x) for x in source_actifs)
    fantomes = sorted(loc - src)
    orphelins = sorted(src - loc)
    apparies = sorted(loc & src)
    return {"coherent": (not fantomes and not orphelins), "fantomes_local_seulement": fantomes,
            "orphelins_source_seulement": orphelins, "apparies": apparies,
            "n_divergences": len(fantomes) + len(orphelins)}


__all__ = ["reconcilier"]
