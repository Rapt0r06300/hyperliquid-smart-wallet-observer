"""[EXEC pépite 211] ZOMBIE-ORDER DETECTOR : un ordre déclaré ANNULÉ localement mais apparaissant encore OPEN/PARTIAL
côté source. On le croit mort ; il vit encore et peut se faire remplir → exposition surprise. On détecte ces zombies
(annulés en local, actifs à la source) pour ré-annuler/réconcilier. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

_ACTIFS = ("OPEN", "PARTIAL", "PARTIALLY_FILLED", "WORKING", "NEW")


def detecter(annules_localement: Iterable[Any], statuts_source: Mapping[str, Any]) -> dict[str, Any]:
    """Zombies = ordres marqués annulés en local dont le statut source est encore actif (OPEN/PARTIAL)."""
    annules = set(str(x) for x in annules_localement)
    zombies = sorted(oid for oid in annules
                     if str(statuts_source.get(oid, "")).upper() in _ACTIFS)
    return {"zombies": zombies, "n": len(zombies), "a_des_zombies": bool(zombies),
            "raison": ("OK" if not zombies else "ORDRES_ANNULES_ENCORE_ACTIFS_SOURCE")}


__all__ = ["detecter"]
