"""[CROSS-VENUE #3] QUOTES SIMULTANÉES : ne jamais comparer un prix vieux de dizaines/centaines de ms à un
prix frais. Les deux jambes doivent être FRAÎCHES au même instant de décision avant tout calcul de spread.

Chaque quote porte son `ts_ms`. On rejette l'opportunité si UNE des jambes dépasse `max_age_ms` vs `now_ms`
(prix périmé). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def quotes_simultanees(quotes: Mapping[str, Mapping[str, Any]], *, now_ms: float,
                       max_age_ms: float = 100.0) -> dict[str, Any]:
    """`quotes` = {venue: {ts_ms, bid, ask}}. Simultanées si CHAQUE jambe est fraîche (now − ts ≤ max_age_ms).
    Une jambe sans ts numérique ou périmée invalide la comparaison (jamais un prix stale comparé à un frais)."""
    ages: dict[str, Any] = {}
    stale: dict[str, Any] = {}
    for venue, q in quotes.items():
        ts = (q or {}).get("ts_ms")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            stale[venue] = "TS_ABSENT"
            continue
        age = float(now_ms) - float(ts)
        ages[venue] = round(age, 4)
        if age < 0 or age > float(max_age_ms):
            stale[venue] = round(age, 4)
    return {"simultanees": (not stale and len(quotes) >= 2), "n_jambes": len(quotes),
            "ages_ms": ages, "stale": stale, "max_age_ms": float(max_age_ms)}


__all__ = ["quotes_simultanees"]
