"""[EXEC pépite 210] MISSING-LOCAL-ORDER DETECTOR : un ordre ACTIF côté source (venue) mais ABSENT de notre state
machine locale. On croit ne pas avoir cet ordre alors qu'il travaille : exposition non suivie. On détecte ces ordres
présents à la source et inconnus en local, pour les adopter/annuler. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def detecter(locaux_connus: Iterable[Any], source_actifs: Iterable[Any]) -> dict[str, Any]:
    """Renvoie les ordres actifs à la source mais absents de notre state machine (à adopter/annuler)."""
    loc = set(str(x) for x in locaux_connus)
    src = set(str(x) for x in source_actifs)
    manquants = sorted(src - loc)
    return {"manquants_en_local": manquants, "n": len(manquants), "a_des_manquants": bool(manquants),
            "raison": ("OK" if not manquants else "ORDRES_SOURCE_INCONNUS_EN_LOCAL")}


__all__ = ["detecter"]
