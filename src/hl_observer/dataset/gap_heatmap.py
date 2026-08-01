"""[DATA pépite 262] GAP HEATMAP : mesurer la DURÉE et la DISTRIBUTION des trous par (venue, coin, channel),
pas juste un compteur global. Dix micro-trous de 5 ms et un trou de 3 h n'ont pas la même conséquence ; un
simple total masque cette différence. On rend, par clé, count / total / p50 / p95 / max pour voir où se
concentre le risque de données. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any


def _percentile(valeurs: list[float], q: float) -> float:
    """Percentile par rang le plus proche (nearest-rank), robuste et sans dépendance externe."""
    if not valeurs:
        return 0.0
    ordonne = sorted(valeurs)
    rang = max(1, math.ceil(q / 100.0 * len(ordonne)))
    return float(ordonne[min(rang, len(ordonne)) - 1])


def heatmap(gaps_par_cle: dict[Any, list]) -> dict[str, Any]:
    """gaps_par_cle = {cle: [durees...]}. Par clé : count, total, p50, p95, max. Durées non finies/négatives
    ignorées (une durée impossible ne gonfle pas la stat). Clé sans trou valide → count 0, stats à 0."""
    resultat: dict[Any, Any] = {}
    for cle, durees in gaps_par_cle.items():
        propres = [float(d) for d in durees
                   if isinstance(d, (int, float)) and not isinstance(d, bool)
                   and math.isfinite(d) and d >= 0]
        resultat[cle] = {
            "count": len(propres),
            "total": round(sum(propres), 6),
            "p50": round(_percentile(propres, 50), 6),
            "p95": round(_percentile(propres, 95), 6),
            "max": round(max(propres), 6) if propres else 0.0,
        }
    return {"heatmap": resultat}


__all__ = ["heatmap"]
