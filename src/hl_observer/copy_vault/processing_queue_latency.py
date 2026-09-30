"""[COPY-VAULT lot2 #45] MESURER LA QUEUE DE TRAITEMENT DU VAULT : on mesure la latence fill_received →
copy_decision (le temps passé dans NOTRE file de traitement CPU), pas seulement la latence réseau. Un backlog CPU
peut retarder la copie bien plus que le réseau, et cette latence-là est invisible si on ne regarde que le réseau.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

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


__all__ = ["latence_traitement_ms", "UNMEASURABLE"]
