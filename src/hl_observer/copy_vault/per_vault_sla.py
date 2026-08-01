"""[COPY-VAULT lot2 #48] SLA PAR VAULT : mesurer la distribution de latence leader_fill → PaperIntent par vault
(p50/p95/p99). Un vault dont la p99 explose est un vault qu'on réplique mal (backlog, source lente) ; le SLA rend
cette dégradation mesurable au lieu de la subir. Pas assez d'échantillons → percentiles UNMEASURABLE. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _percentile(tries: list[float], q: float) -> float:
    """Percentile par plus proche rang sur une liste triée (q dans [0,1])."""
    if not tries:
        return 0.0
    rang = max(0, min(len(tries) - 1, int(round(q * (len(tries) - 1)))))
    return tries[rang]


class SLAVault:
    """Accumule les latences fill→intent par vault et expose p50/p95/p99."""

    def __init__(self) -> None:
        self._latences: dict[str, list[float]] = {}

    def enregistrer(self, vault: str, latence_ms: Any) -> bool:
        if not isinstance(latence_ms, (int, float)) or float(latence_ms) < 0:
            return False
        self._latences.setdefault(str(vault), []).append(float(latence_ms))
        return True

    def sla(self, vault: str, *, min_echantillons: int = 5) -> dict[str, Any]:
        xs = sorted(self._latences.get(str(vault), []))
        if len(xs) < int(min_echantillons):
            return {"p50": UNMEASURABLE, "p95": UNMEASURABLE, "p99": UNMEASURABLE, "n": len(xs),
                    "raison": "ECHANTILLON_INSUFFISANT"}
        return {"p50": round(_percentile(xs, 0.50), 3), "p95": round(_percentile(xs, 0.95), 3),
                "p99": round(_percentile(xs, 0.99), 3), "n": len(xs)}


__all__ = ["SLAVault", "UNMEASURABLE"]
