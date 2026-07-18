"""K4 — CADENCE DE RE-FIT + MONITEUR DE DÉCROISSANCE.

Ré-entraîner trop souvent = sur-ajuster le bruit récent ; trop rarement = le modèle décroche quand
le marché change. On re-fit sur cadence (temps écoulé) OU si la perf récente DÉCROCHE sous un seuil.
Le moniteur de décroissance compare la perf récente à la perf de référence (in-sample). PAPER only.
"""
from __future__ import annotations

from typing import Sequence

RESTE = "RESTE"
REFIT_CADENCE = "REFIT_CADENCE"
REFIT_DECROISSANCE = "REFIT_DECROISSANCE"


def decroissance_detectee(perf_reference: float, perf_recente: float, *, fraction_min: float = 0.5) -> bool:
    """True si la perf récente est tombée sous `fraction_min` × la perf de référence (edge qui décroche).
    Réf <= 0 -> pas de décroissance mesurable (on ne juge pas)."""
    if float(perf_reference) <= 0.0:
        return False
    return float(perf_recente) < float(fraction_min) * float(perf_reference)


def decision_refit(now_ms: int, dernier_fit_ms: int, *, intervalle_ms: float,
                   perf_reference: float | None = None, perf_recente: float | None = None,
                   fraction_min: float = 0.5) -> str:
    """REFIT_DECROISSANCE si la perf décroche ; sinon REFIT_CADENCE si l'intervalle est dépassé ; sinon RESTE."""
    if perf_reference is not None and perf_recente is not None \
            and decroissance_detectee(perf_reference, perf_recente, fraction_min=fraction_min):
        return REFIT_DECROISSANCE
    if int(now_ms) - int(dernier_fit_ms) >= float(intervalle_ms):
        return REFIT_CADENCE
    return RESTE


__all__ = ["RESTE", "REFIT_CADENCE", "REFIT_DECROISSANCE", "decroissance_detectee", "decision_refit"]
