"""ALPHA P38 — CLOCK REGIMES comme FILTRE : début seconde/minute/5m/15m/heure/sessions UTC.

Certaines fenêtres d'horloge concentrent l'edge (frontières de bougie, sessions). On teste ces buckets
UNIQUEMENT comme filtre, avec correction multiple-testing OBLIGATOIRE (plus on teste de buckets, plus le
seuil monte). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.research.validation_gates import attendu_max_bruit_bps

GRANULARITES_MS = {"seconde": 1000, "minute": 60_000, "5m": 300_000, "15m": 900_000, "heure": 3_600_000}


def bucket_horloge(ts_ms: int, granularite: str) -> int:
    """Position dans la fenêtre : ms écoulées depuis le début de la granularité (proximité de la frontière)."""
    g = GRANULARITES_MS.get(granularite, 60_000)
    return int(ts_ms) % g


def session_utc(ts_ms: int) -> str:
    """Session grossière (asie/europe/us) selon l'heure UTC."""
    h = (int(ts_ms) // 3_600_000) % 24
    if h < 8:
        return "ASIE"
    if h < 16:
        return "EUROPE"
    return "US"


def tester_buckets(markouts_par_bucket: Mapping[Any, Sequence[float]], *, sigma_bps: float | None = None) -> dict[str, Any]:
    """Net moyen par bucket + meilleur bucket avec correction multiple-testing (E[max de N bruits])."""
    nets = {}
    for b, v in markouts_par_bucket.items():
        vv = [float(x) for x in v]
        nets[b] = round(statistics.mean(vv), 4) if len(vv) >= 5 else None
    mesurables = {b: n for b, n in nets.items() if n is not None}
    if not mesurables:
        return {"nets_par_bucket": nets, "meilleur": None, "verdict": "MORE_DATA"}
    best_b = max(mesurables, key=lambda b: mesurables[b])
    n_tests = len(mesurables)
    if sigma_bps is None:
        toutes = [x for v in markouts_par_bucket.values() for x in v]
        sigma_bps = statistics.pstdev(toutes) if len(toutes) > 2 else 1.0
    seuil = attendu_max_bruit_bps(n_tests, sigma_bps / max(1.0, len(next(iter(markouts_par_bucket.values()))) ** 0.5))
    survit = mesurables[best_b] > seuil
    return {"nets_par_bucket": nets, "meilleur": best_b, "net_meilleur_bps": mesurables[best_b],
            "seuil_multiple_testing_bps": round(seuil, 4), "n_tests": n_tests,
            "verdict": ("FILTRE_UTILE" if survit else "BRUIT_MULTIPLE_TESTING")}


__all__ = ["GRANULARITES_MS", "bucket_horloge", "session_utc", "tester_buckets"]
