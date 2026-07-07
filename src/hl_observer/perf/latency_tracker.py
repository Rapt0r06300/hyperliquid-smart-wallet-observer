"""PERF-1 — Instrumentation latence bout-en-bout (mesurer AVANT d'optimiser).

Chaque décision traverse des étages: fill leader observé → détecté (WS) →
décision → paper fill. On horodate chaque étage et on agrège en percentiles
p50/p95/p99 par étage. Pur, sans I/O, thread-safe: destiné à être appelé depuis
le tick engine et lu par le dashboard (PERF-5 en dérive un budget dynamique).

Aucune donnée inventée: un étage sans mesure n'apparaît pas.
"""

from __future__ import annotations

import threading
from bisect import insort

STAGES = ("leader_to_detect", "detect_to_decision", "decision_to_fill", "end_to_end")


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 3)
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return round(sorted_vals[idx], 3)


class LatencyTracker:
    def __init__(self, max_per_stage: int = 5_000) -> None:
        self._lock = threading.Lock()
        self._samples: dict[str, list[float]] = {s: [] for s in STAGES}
        self._max = int(max_per_stage)

    def record_stage(self, stage: str, ms: float) -> None:
        if stage not in self._samples or ms is None:
            return
        try:
            v = float(ms)
        except (TypeError, ValueError):
            return
        if v < 0:
            return
        with self._lock:
            buf = self._samples[stage]
            insort(buf, v)
            if len(buf) > self._max:
                buf.pop(len(buf) // 2)  # évincer autour de la médiane: garde les queues

    def record_decision(self, *, leader_ms: float, detect_ms: float, decision_ms: float, fill_ms: float) -> None:
        """Enregistre les 4 timestamps (epoch ms) d'une décision et dérive les étages."""
        if None in (leader_ms, detect_ms, decision_ms, fill_ms):
            return
        self.record_stage("leader_to_detect", detect_ms - leader_ms)
        self.record_stage("detect_to_decision", decision_ms - detect_ms)
        self.record_stage("decision_to_fill", fill_ms - decision_ms)
        self.record_stage("end_to_end", fill_ms - leader_ms)

    def report(self) -> dict:
        out: dict[str, dict] = {}
        with self._lock:
            for stage, buf in self._samples.items():
                if not buf:
                    out[stage] = {"n": 0, "p50": None, "p95": None, "p99": None, "max": None}
                    continue
                out[stage] = {
                    "n": len(buf),
                    "p50": _pct(buf, 0.50),
                    "p95": _pct(buf, 0.95),
                    "p99": _pct(buf, 0.99),
                    "max": round(buf[-1], 3),
                }
        e2e = out.get("end_to_end", {})
        out["targets"] = {
            "detect_under_1s": (e2e.get("p95") or 0) <= 1_000 if e2e.get("n") else None,
            "decision_under_100ms": (out.get("detect_to_decision", {}).get("p95") or 0) <= 100 if out.get("detect_to_decision", {}).get("n") else None,
        }
        return out

    def reset(self) -> None:
        with self._lock:
            for s in self._samples:
                self._samples[s] = []


_SHARED: LatencyTracker | None = None


def get_latency_tracker() -> LatencyTracker:
    global _SHARED
    if _SHARED is None:
        _SHARED = LatencyTracker()
    return _SHARED


__all__ = ["STAGES", "LatencyTracker", "get_latency_tracker"]
