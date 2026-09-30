"""[DATA lot2 #67] receipt_timestamp SYSTÉMATIQUE : chaque message porte un receipt_timestamp (l'instant où NOUS
l'avons reçu), SÉPARÉ du timestamp exchange (l'instant où la venue l'a émis). La différence des deux mesure la
latence de bout en bout — impossible à calculer si on ne garde qu'un seul horodatage (Cryptofeed l'a ajouté partout).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def annoter(message: Any, *, receipt_ts_ms: Any, exchange_ts_ms: Any = None) -> dict[str, Any]:
    """Attache receipt_ts (obligatoire) et exchange_ts (optionnel). Latence = receipt − exchange si les deux
    existent, sinon UNMEASURABLE (jamais 0 supposé). receipt manquant → message rejeté (non horodatable)."""
    if not isinstance(receipt_ts_ms, (int, float)):
        return {"ok": False, "raison": "RECEIPT_TS_MANQUANT"}
    latence = (round(float(receipt_ts_ms) - float(exchange_ts_ms), 3)
               if isinstance(exchange_ts_ms, (int, float)) else UNMEASURABLE)
    return {"ok": True, "message": message, "receipt_ts_ms": float(receipt_ts_ms),
            "exchange_ts_ms": (float(exchange_ts_ms) if isinstance(exchange_ts_ms, (int, float)) else None),
            "latence_ms": latence}


__all__ = ["annoter", "UNMEASURABLE"]
