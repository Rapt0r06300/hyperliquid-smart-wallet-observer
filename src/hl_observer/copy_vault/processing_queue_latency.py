"""[COPY-VAULT lot2 #45] MESURER LA QUEUE DE TRAITEMENT DU VAULT : on mesure la latence fill_received →
copy_decision (le temps passé dans NOTRE file de traitement CPU), pas seulement la latence réseau. Un backlog CPU
peut retarder la copie bien plus que le réseau, et cette latence-là est invisible si on ne regarde que le réseau.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def latence_traitement_ms(fill_received_ms: Any, copy_decision_ms: Any) -> dict[str, Any]:
    """Latence interne = copy_decision − fill_received. Négative (décision avant réception ?) ou invalide →
    UNMEASURABLE (jamais 0 supposé)."""
    if not all(isinstance(x, (int, float)) for x in (fill_received_ms, copy_decision_ms)):
        return {"latence_ms": UNMEASURABLE, "raison": "HORODATAGE_INVALIDE"}
    d = float(copy_decision_ms) - float(fill_received_ms)
    if d < 0:
        return {"latence_ms": UNMEASURABLE, "raison": "DECISION_AVANT_RECEPTION"}
    return {"latence_ms": round(d, 3), "composante": "queue_cpu_interne"}


def queue_latency_profile(received_to_decision_ms: list[Any]) -> dict[str, Any]:
    """Compute p50/p95/p99 from observed receive-to-decision samples only."""
    if not isinstance(received_to_decision_ms, list) or not received_to_decision_ms:
        return {"status": "MORE_DATA", "reason": "latency_samples_missing"}
    values: list[float] = []
    for value in received_to_decision_ms:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            return {"status": UNMEASURABLE, "reason": "invalid_latency_sample"}
        values.append(float(value))
    values.sort()
    def quantile(q: float) -> float:
        index = max(0, min(len(values) - 1, math.ceil(q * len(values)) - 1))
        return round(values[index], 6)
    return {"status": "PROVEN", "count": len(values), "p50_ms": quantile(0.50),
            "p95_ms": quantile(0.95), "p99_ms": quantile(0.99),
            "source": "received_to_decision_observed"}


__all__ = ["latence_traitement_ms", "queue_latency_profile", "UNMEASURABLE"]
