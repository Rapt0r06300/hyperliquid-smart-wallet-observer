"""[COPY-VAULT lot2 #59] POSITION-STATE HASH : un hash DÉTERMINISTE de TOUTES les positions du vault, stocké
périodiquement, pour détecter toute DIVERGENCE de replay (si on rejoue les fills et qu'on n'obtient pas le même
hash, le replay a divergé de la réalité). Le hash est stable quel que soit l'ordre d'itération. Pur, 0 réseau.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

_TOL_DECIMALES = 10


def hash_positions(positions: Mapping[str, Any]) -> str:
    """Hash déterministe des positions {coin: taille}. Coins triés, tailles arrondies : deux états identiques →
    même hash, indépendamment de l'ordre d'insertion. Valeurs non numériques ignorées explicitement (marquées)."""
    items = []
    for coin in sorted(str(k).upper() for k in positions.keys()):
        v = positions.get(coin) if coin in positions else None
        if v is None:
            # récupère la valeur d'origine (clé peut différer en casse)
            for k in positions:
                if str(k).upper() == coin:
                    v = positions[k]
                    break
        val = round(float(v), _TOL_DECIMALES) if isinstance(v, (int, float)) else "NA"
        items.append("%s:%s" % (coin, val))
    brut = "|".join(items)
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()


def concordent(hash_a: Any, hash_b: Any) -> dict[str, Any]:
    """Vrai si les deux hash existent ET sont égaux. Un hash absent → divergence présumée (fail-closed)."""
    if hash_a is None or hash_b is None:
        return {"concordent": False, "raison": "HASH_ABSENT"}
    ok = str(hash_a) == str(hash_b)
    return {"concordent": bool(ok), "raison": ("OK" if ok else "DIVERGENCE_REPLAY")}


__all__ = ["hash_positions", "concordent"]
