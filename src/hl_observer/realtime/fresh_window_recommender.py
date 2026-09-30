"""D1 — Recommander une fenêtre de fraîcheur à partir de la latence mesurée.

Lit une distribution de latences (ms) et propose une fenêtre fraîche = p90 × marge.
Pur. La MESURE réelle vient d'un run (realtime/latency_report). Ne trade pas.
"""

from __future__ import annotations


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def recommend_fresh_window_ms(latency_samples_ms, *, safety_mult: float = 1.5, floor_ms: float = 2000.0) -> dict:
    vals = sorted(float(x) for x in latency_samples_ms if x is not None and float(x) >= 0)
    if not vals:
        return {"status": "INSUFFICIENT_DATA", "recommended_fresh_window_ms": None, "n": 0}
    p50, p90, p99 = _percentile(vals, 50), _percentile(vals, 90), _percentile(vals, 99)
    rec = max(floor_ms, p90 * float(safety_mult))
    return {
        "status": "OK",
        "n": len(vals),
        "p50_ms": round(p50, 1), "p90_ms": round(p90, 1), "p99_ms": round(p99, 1),
        "recommended_fresh_window_ms": round(rec, 1),
        "note": "Fenêtre >= p90 latence x marge. Entrer hors de cette fenêtre = edge déjà mangé.",
    }


__all__ = ["recommend_fresh_window_ms"]
