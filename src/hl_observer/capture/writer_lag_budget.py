"""[DATA pépite 275] WRITER-LAG BUDGET : on mesure le délai event_received → durable_write. Si le disque
ralentit trop (lag au-delà du budget), l'état de capture est déclaré DÉGRADÉ — on sait alors que le journal
durable prend du retard et qu'un crash perdrait davantage d'événements. Un lag négatif (horloges incohérentes)
est traité comme invalide, donc dégradé (fail-closed). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

OK = "OK"
DEGRADE = "DEGRADE"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def evaluer(t_recu: Any, t_ecrit_durable: Any, *, budget_ms: float = 250.0) -> dict[str, Any]:
    """lag = t_ecrit_durable - t_recu. lag ≤ budget → OK. lag > budget → DEGRADE. Entrées non finies ou lag
    négatif → DEGRADE (invalide, on ne suppose pas que tout va bien)."""
    if not (_fini(t_recu) and _fini(t_ecrit_durable)):
        return {"etat": DEGRADE, "lag_ms": None, "raison": "HORODATAGE_INVALIDE"}
    lag = float(t_ecrit_durable) - float(t_recu)
    if lag < 0:
        return {"etat": DEGRADE, "lag_ms": round(lag, 6), "raison": "LAG_NEGATIF"}
    if lag > float(budget_ms):
        return {"etat": DEGRADE, "lag_ms": round(lag, 6), "raison": "BUDGET_DEPASSE"}
    return {"etat": OK, "lag_ms": round(lag, 6)}


__all__ = ["evaluer", "OK", "DEGRADE"]
