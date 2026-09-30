"""[CROSS-VENUE #4] MAXIMUM QUOTE SKEW : une opportunité devient invalide si l'écart temporel entre les deux
jambes, abs(ts_A − ts_B), dépasse une limite propre au marché (les deux prix ne sont plus « du même instant »).

Distinct de la fraîcheur absolue (#3) : ici c'est l'écart RELATIF entre les deux quotes qui compte.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def skew_acceptable(ts_a: Any, ts_b: Any, *, max_skew_ms: float) -> dict[str, Any]:
    """Rejette si abs(ts_A − ts_B) > max_skew_ms. Un ts manquant/non numérique = non mesurable → rejeté."""
    if not all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in (ts_a, ts_b)):
        return {"ok": False, "skew_ms": None, "raison": "TS_NON_MESURABLE", "max_skew_ms": float(max_skew_ms)}
    skew = abs(float(ts_a) - float(ts_b))
    return {"ok": bool(skew <= float(max_skew_ms)), "skew_ms": round(skew, 4),
            "max_skew_ms": float(max_skew_ms),
            "raison": ("OK" if skew <= float(max_skew_ms) else "SKEW_TROP_GRAND")}


__all__ = ["skew_acceptable"]
