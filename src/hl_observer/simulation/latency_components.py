"""AUD-155 — latences SEPAREES : feed / order / inter-leg (jamais un blob unique).

La latence d'un round-trip paper se decompose en composantes DISTINCTES et mesurables : FEED
(donnee->decision), ORDRE (decision->fill), INTER-JAMBES (cross-venue). Chacune est exposee ; le
total = leur somme. Une composante None = UNMEASURABLE (jamais 0). Read-only.
"""
from __future__ import annotations

COMPOSANTES = ("feed_ms", "order_ms", "inter_leg_ms")


def decomposer_latence(*, feed_ms=None, order_ms=None, inter_leg_ms=None) -> dict:
    comp = {"feed_ms": feed_ms, "order_ms": order_ms, "inter_leg_ms": inter_leg_ms}
    manquantes = [k for k, v in comp.items() if v is None]
    total = None if manquantes else round(sum(float(v) for v in comp.values()), 6)
    return {"composantes": {k: (None if v is None else float(v)) for k, v in comp.items()},
            "total_ms": total, "manquantes": manquantes, "mesurable": not manquantes}


__all__ = ["decomposer_latence", "COMPOSANTES"]
