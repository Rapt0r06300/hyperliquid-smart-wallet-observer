"""[ARB pépite 235] ROUTE SCORE PAR TIMEOUT p99 : intégrer dans le score d'une route les DÉLAIS EXTRÊMES de
confirmation (timeout p99), pas seulement la latence médiane. Une route rapide en médiane mais qui bloque parfois
plusieurs secondes expose la jambe orpheline au gap-risk pendant ce temps. Le p99 capture ce pire cas. Pas assez
d'échantillons → non mesurable. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _percentile(tries: list[float], q: float) -> float:
    if not tries:
        return 0.0
    rang = max(0, min(len(tries) - 1, int(round(q * (len(tries) - 1)))))
    return tries[rang]


def score_p99(latences_ms: Sequence[Any], *, min_echantillons: int = 20) -> dict[str, Any]:
    """Renvoie le timeout p99 d'une route (plus bas = meilleur) ainsi que la médiane pour contraste. Trop peu
    d'échantillons → UNMEASURABLE (on ne score pas une route sur trop peu de mesures)."""
    xs = sorted(float(x) for x in latences_ms if isinstance(x, (int, float)) and x >= 0)
    if len(xs) < int(min_echantillons):
        return {"p99_ms": UNMEASURABLE, "n": len(xs), "raison": "ECHANTILLON_INSUFFISANT"}
    return {"p99_ms": round(_percentile(xs, 0.99), 3), "p50_ms": round(_percentile(xs, 0.50), 3), "n": len(xs)}


__all__ = ["score_p99", "UNMEASURABLE"]
