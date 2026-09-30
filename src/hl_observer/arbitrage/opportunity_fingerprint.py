"""[ARB #28] OPPORTUNITY FINGERPRINT : dédupliquer une MÊME dislocation détectée par plusieurs boucles via une
empreinte stable {coin, venues (triées), direction, price-state, time bucket}. Deux détections de la même
dislocation dans la même fenêtre temporelle produisent la MÊME empreinte → un seul épisode. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any


def fingerprint(*, coin: str, venues: Iterable[str], direction: Any, price_state: Any, ts_ms: float,
                bucket_ms: float = 1000.0) -> str:
    """Empreinte déterministe : mêmes coin/venues/direction/price_state dans le même bucket temporel → même hash."""
    v = ",".join(sorted(str(x).upper() for x in venues))
    bucket = int(float(ts_ms) // float(bucket_ms))
    brut = "|".join([str(coin).upper(), v, str(direction).upper(), str(price_state), str(bucket)])
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()[:16]


__all__ = ["fingerprint"]
