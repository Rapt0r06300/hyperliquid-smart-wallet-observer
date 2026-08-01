"""Rapport de benchmark de latence de copie : agrège des `CopyLatencyProfile` (mesures réelles
leader→observé→décision) en un résumé lisible pour le dashboard/audit. Lecture seule, 0 réseau, 0 ordre.

Câblé par `copy_mode.copy_latency_profiler` (producteur des profils). Toute valeur manquante (None) est
ignorée honnêtement dans les agrégats — jamais remplacée par un zéro trompeur.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence


def _valeurs(profiles: Iterable[Any], attr: str) -> list[int]:
    out: list[int] = []
    for p in profiles:
        v = getattr(p, attr, None)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(int(v))
    return out


def _percentile(valeurs: Sequence[int], q: float) -> int | None:
    """Percentile par rang (interpolation linéaire), mémoire bornée. Liste vide → None (jamais 0)."""
    if not valeurs:
        return None
    xs = sorted(valeurs)
    if len(xs) == 1:
        return int(xs[0])
    rang = min(max(q, 0.0), 1.0) * (len(xs) - 1)
    bas = int(rang)
    haut = min(bas + 1, len(xs) - 1)
    frac = rang - bas
    return int(round(xs[bas] + (xs[haut] - xs[bas]) * frac))


def build_latency_benchmark_report(profiles: Iterable[Any]) -> dict[str, Any]:
    """Agrège une liste de `CopyLatencyProfile`. Rend samples, max/min/moyenne/p50/p95 du total_ms, et le
    nombre de profils portant un `warning` (latence lente / temps leader manquant)."""
    profiles = list(profiles or [])
    totaux = _valeurs(profiles, "total_ms")
    warnings = [getattr(p, "warning", None) for p in profiles]
    warning_count = sum(1 for w in warnings if w)
    moyenne = (sum(totaux) / len(totaux)) if totaux else None
    return {
        "samples": len(profiles),
        "mesures_total_ms": len(totaux),
        "max_total_ms": max(totaux) if totaux else None,
        "min_total_ms": min(totaux) if totaux else None,
        "avg_total_ms": round(moyenne, 2) if moyenne is not None else None,
        "p50_total_ms": _percentile(totaux, 0.50),
        "p95_total_ms": _percentile(totaux, 0.95),
        "warning_count": warning_count,
        "warnings": sorted({str(w) for w in warnings if w}),
        "real_execution": False,
    }


__all__ = ["build_latency_benchmark_report"]
