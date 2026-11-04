"""[COPY-VAULT pépite 297] COPYABILITY EROSION MONITOR : on suit l'écart (edge post-fill du leader − notre edge
de copie réalisé). Un vault peut rester rentable POUR LUI tout en devenant de moins en moins copiable pour nous
(latence, impact, file d'attente) : si cet écart AUGMENTE durablement, le vault est déclassé — son alpha ne nous
parvient plus. On compare la moitié récente des écarts à la moitié ancienne. Données insuffisantes → pas de
verdict (honnête). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any


class MoniteurErosion:
    """Accumule des écarts leader_edge − notre_edge. verdict() déclasse si l'écart moyen récent dépasse
    l'ancien de plus de seuil_hausse ET reste positif (le leader gagne alors que nous, non). Prudent : sans
    assez d'échantillons, aucun déclassement (on ne condamne pas sur du bruit)."""

    def __init__(self, min_echantillons: int = 4, seuil_hausse: float = 0.0) -> None:
        self._gaps: list[float] = []
        self._min = max(2, int(min_echantillons))
        self._seuil = float(seuil_hausse)

    def observer(self, leader_edge: Any, notre_edge: Any) -> dict[str, Any]:
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                   for x in (leader_edge, notre_edge)):
            return {"ok": False, "raison": "EDGE_INVALIDE"}
        gap = float(leader_edge) - float(notre_edge)
        self._gaps.append(gap)
        return {"ok": True, "gap": round(gap, 8), "n": len(self._gaps)}

    def verdict(self) -> dict[str, Any]:
        n = len(self._gaps)
        if n < self._min:
            return {"declasse": False, "raison": "DONNEES_INSUFFISANTES", "n": n}
        moitie = n // 2
        vieux = sum(self._gaps[:moitie]) / moitie
        recent = sum(self._gaps[moitie:]) / (n - moitie)
        hausse = recent - vieux
        declasse = hausse > self._seuil and recent > 0
        return {"declasse": declasse, "hausse": round(hausse, 8), "gap_recent": round(recent, 8),
                "gap_ancien": round(vieux, 8), "raison": "EROSION_COPYABILITE" if declasse else None}


def erosion_receipt(
    observations: list[tuple[Any, Any]], *, min_samples: int = 4, threshold: float = 0.0
) -> dict[str, Any]:
    """Compare old/recent net gaps and remain MORE_DATA below the sample gate."""
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 2:
        return {"status": "UNMEASURABLE", "reason": "min_samples_must_be_at_least_two"}
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not math.isfinite(float(threshold)):
        return {"status": "UNMEASURABLE", "reason": "threshold_must_be_finite"}
    monitor = MoniteurErosion(min_echantillons=min_samples, seuil_hausse=float(threshold))
    for leader_edge, copy_edge in observations:
        observed = monitor.observer(leader_edge, copy_edge)
        if not observed.get("ok"):
            return {"status": "UNMEASURABLE", "reason": observed["raison"]}
    verdict = monitor.verdict()
    return {"status": "PROVEN" if len(observations) >= min_samples else "MORE_DATA",
            "samples": len(observations), "copyability_erosion": bool(verdict.get("declasse")),
            "verdict": verdict}


__all__ = ["MoniteurErosion", "erosion_receipt"]
