"""AUD-155 — latences SEPAREES : feed / order / inter-leg (jamais un blob unique).

La latence d'un round-trip paper se decompose en composantes DISTINCTES et mesurables : FEED
(donnee->decision), ORDRE (decision->fill), INTER-JAMBES (cross-venue). Chacune est exposee ; le
total = leur somme. Une composante None = UNMEASURABLE (jamais 0). Read-only.
"""
from __future__ import annotations

import math

COMPOSANTES = ("feed_ms", "order_ms", "intedef decomposer_latence(*, feed_ms=None, order_ms=None, inter_leg_ms=None) -> dict:
    comp = {"feed_ms": feed_ms, "order_ms": order_ms, "inter_leg_ms": inter_leg_ms}
    manquantes = []
    invalides = []
    normalized = {}
    for key, value in comp.items():
        if value is None:
            manquantes.append(key)
            normalized[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalides.append({"component": key, "reason": "NON_NUMERIC"})
            normalized[key] = None
            continue
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            invalides.append({"component": key, "reason": "NON_FINITE_OR_NEGATIVE"})
            normalized[key] = None
            continue
        normalized[key] = numeric
    total = (
        round(sum(normalized.values()), 6)
        if not manquantes and not invalides
        else None
    )
    return {
        "composantes": normalized,
        "total_ms": total,
        "manquantes": manquantes,
        "invalides": invalides,
        "mesurable": not manquantes and not invalides,
    }
t manquantes}


__all__ = ["decomposer_latence", "COMPOSANTES"]
