"""[DATA lot2 #29] CONNECTION SHARDING : distribuer les symboles/channels sur PLUSIEURS connexions quand un flux
devient trop lourd (gros univers de symboles) pour qu'une seule connexion ne sature pas et ne prenne pas de retard
(Cryptofeed). On répartit équitablement (round-robin) sur N shards. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def repartir(symboles: Sequence[Any], *, n_shards: int) -> dict[str, Any]:
    """Répartit les symboles sur n_shards connexions en round-robin (charge équilibrée). n_shards invalide →
    UNMEASURABLE."""
    if not isinstance(n_shards, int) or n_shards <= 0:
        return {"shards": "UNMEASURABLE", "raison": "N_SHARDS_INVALIDE"}
    shards: list[list[Any]] = [[] for _ in range(n_shards)]
    for i, s in enumerate(symboles):
        shards[i % n_shards].append(s)
    tailles = [len(sh) for sh in shards]
    equilibre = (max(tailles) - min(tailles)) <= 1 if tailles else True
    return {"shards": shards, "n_shards": n_shards, "tailles": tailles, "equilibre": bool(equilibre)}


__all__ = ["repartir"]
