"""[ARB pépite 234] ROUTE SCORE PAR SHORTFALL p95 : deux venues aux MÊMES frais ne sont PAS équivalentes si l'une
dérape davantage dans la QUEUE de distribution. On score chaque route par son shortfall p95 (le 95ᵉ percentile de
l'écart prix réel vs attendu) — ce qui capture le mauvais cas, pas seulement la médiane. Pas assez d'échantillons →
score non mesurable. Pur, 0 réseau, 0 ordre réel.
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


def score_p95(shortfalls_bps: Sequence[Any], *, min_echantillons: int = 20) -> dict[str, Any]:
    """Renvoie le shortfall p95 d'une route (plus bas = meilleur). Trop peu d'échantillons → UNMEASURABLE."""
    xs = sorted(float(x) for x in shortfalls_bps if isinstance(x, (int, float)))
    if len(xs) < int(min_echantillons):
        return {"p95_bps": UNMEASURABLE, "n": len(xs), "raison": "ECHANTILLON_INSUFFISANT"}
    return {"p95_bps": round(_percentile(xs, 0.95), 4), "p50_bps": round(_percentile(xs, 0.50), 4), "n": len(xs)}


def meilleure(*, route_a_p95: Any, route_b_p95: Any) -> dict[str, Any]:
    """Compare deux routes par shortfall p95 (plus bas = mieux). p95 non mesurable → route écartée."""
    if not isinstance(route_a_p95, (int, float)):
        return {"meilleure": "B" if isinstance(route_b_p95, (int, float)) else "AUCUNE"}
    if not isinstance(route_b_p95, (int, float)):
        return {"meilleure": "A"}
    return {"meilleure": ("A" if float(route_a_p95) <= float(route_b_p95) else "B")}


__all__ = ["score_p95", "meilleure", "UNMEASURABLE"]
