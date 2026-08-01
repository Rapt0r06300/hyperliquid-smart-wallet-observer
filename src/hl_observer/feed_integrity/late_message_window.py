"""[DATA pépite 271] LATE-MESSAGE WINDOW : les messages hors ordre restent TEMPORAIREMENT dans une petite
fenêtre de réordonnancement (reorder window) ; s'ils sont trop tardifs (au-delà de la fenêtre par rapport au
dernier timestamp traité), ils sont LOGGÉS mais PAS injectés causalement — on ne réécrit pas le passé déjà
consommé. Un message dans l'ordre passe directement. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

OK = "OK"
REORDONNE = "REORDONNE"
REJETE_TROP_TARD = "REJETE_TROP_TARD"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def classer(ts_message: Any, dernier_ts_traite: Any, *, fenetre_ms: float = 20.0) -> dict[str, Any]:
    """ts ≥ dernier → OK (dans l'ordre). dernier - fenetre ≤ ts < dernier → REORDONNE (à replacer dans la
    fenêtre). ts < dernier - fenetre → REJETE_TROP_TARD (loggé, jamais injecté causalement). Non fini → rejet."""
    if not (_fini(ts_message) and _fini(dernier_ts_traite)):
        return {"action": REJETE_TROP_TARD, "raison": "TIMESTAMP_INVALIDE"}
    ts = float(ts_message)
    dernier = float(dernier_ts_traite)
    if ts >= dernier:
        return {"action": OK, "retard_ms": 0.0}
    retard = dernier - ts
    if retard <= float(fenetre_ms):
        return {"action": REORDONNE, "retard_ms": round(retard, 6)}
    return {"action": REJETE_TROP_TARD, "retard_ms": round(retard, 6), "raison": "HORS_FENETRE"}


__all__ = ["classer", "OK", "REORDONNE", "REJETE_TROP_TARD"]
