"""[CABLAGE Lead-Lag] LEAD-LAG STAGE : mesure si la DIRECTION des fills leader PRÉCÈDE le mouvement du mid (le
leader anticipe-t-il le move ?). C'est le 3e module d'alpha du chemin canonique, à côté de Copy-Vault et
Cross-Venue. Score = fraction de paires (signe_leader, Δmid_futur) alignées, et edge moyen en bps. Sans paires
mesurées (données absentes) → UNMEASURABLE (jamais un edge inventé). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def score_lead_lag(paires: list[tuple[Any, Any]], *, min_echantillons: int = 20,
                   seuil_edge_bps: float = 0.0) -> dict[str, Any]:
    """paires = [(signe_leader ∈ {-1,+1}, delta_mid_futur signé)]. Alignement = signe_leader × Δmid > 0 (le
    leader va dans le sens du move suivant). Rend {score, edge_bps_moyen, n, predictif}. Échantillon insuffisant
    ou aucune paire valide → UNMEASURABLE."""
    valides = [(1.0 if s > 0 else -1.0, float(d)) for s, d in paires
               if _fini(s) and s != 0 and _fini(d)]
    n = len(valides)
    if n < min_echantillons:
        return {"score": UNMEASURABLE, "edge_bps_moyen": UNMEASURABLE, "n": n,
                "raison": "ECHANTILLON_INSUFFISANT"}
    alignes = [s * d for s, d in valides]
    score = sum(1 for a in alignes if a > 0) / n
    edge = sum(alignes) / n
    predictif = score > 0.5 and edge > seuil_edge_bps
    return {"score": round(score, 6), "edge_bps_moyen": round(edge, 6), "n": n,
            "predictif": predictif}


__all__ = ["score_lead_lag", "UNMEASURABLE"]
