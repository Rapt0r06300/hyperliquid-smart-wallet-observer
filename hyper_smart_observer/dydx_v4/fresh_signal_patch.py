from __future__ import annotations

import time
from typing import Any

DEFAULT_CONFIRMATION_WINDOW_MS = 30_000
DEFAULT_SPREAD_LIMIT_MS = 180_000


def effective_cluster_age_ms(cluster: Any, now_ms: int | None = None) -> int:
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    raw_age = max(0, int(getattr(cluster, "signal_age_ms", 0) or 0))
    first_ms = int(getattr(cluster, "first_wallet_opened_ms", 0) or 0)
    last_ms = int(getattr(cluster, "last_wallet_opened_ms", 0) or 0)
    wallet_count = int(getattr(cluster, "wallet_count", 0) or 0)
    if wallet_count < 2 or last_ms <= 0:
        return raw_age
    last_age = max(0, now - last_ms)
    spread = max(0, last_ms - first_ms) if first_ms > 0 else 0
    if last_age <= DEFAULT_CONFIRMATION_WINDOW_MS and spread <= DEFAULT_SPREAD_LIMIT_MS:
        return min(raw_age, last_age)
    return raw_age


def freshness_penalty_bps(cluster: Any) -> float:
    raw = max(0, int(getattr(cluster, "raw_signal_age_ms", getattr(cluster, "signal_age_ms", 0)) or 0))
    eff = max(0, int(getattr(cluster, "signal_age_ms", 0) or 0))
    if raw <= eff:
        return 0.0
    delayed_s = (raw - eff) / 1000.0
    return round(min(18.0, delayed_s * 0.08), 4)


def apply_freshness_recovery(cluster: Any, now_ms: int | None = None) -> Any:
    raw_age = max(0, int(getattr(cluster, "signal_age_ms", 0) or 0))
    effective_age = effective_cluster_age_ms(cluster, now_ms=now_ms)
    setattr(cluster, "raw_signal_age_ms", raw_age)
    setattr(cluster, "effective_signal_age_ms", effective_age)
    setattr(cluster, "freshness_recovered", effective_age < raw_age)
    if effective_age < raw_age:
        cluster.signal_age_ms = effective_age
        old_strength = float(getattr(cluster, "signal_strength", 0.0) or 0.0)
        penalty = min(0.18, freshness_penalty_bps(cluster) / 100.0)
        cluster.signal_strength = max(0.0, min(1.0, old_strength - penalty))
        setattr(cluster, "freshness_penalty_bps", freshness_penalty_bps(cluster))
    return cluster


def install_fresh_signal_patch() -> None:
    try:
        from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
    except Exception:
        return
    if getattr(DydxClusterDetector, "_fresh_signal_patch_installed", False):
        return
    original = DydxClusterDetector.detect_clusters

    def detect_clusters_fresh(self, *args, **kwargs):
        clusters = list(original(self, *args, **kwargs))
        now_ms = int(time.time() * 1000)
        for cluster in clusters:
            try:
                apply_freshness_recovery(cluster, now_ms=now_ms)
            except Exception:
                continue
        clusters.sort(key=lambda c: (getattr(c, "signal_strength", 0.0), -getattr(c, "signal_age_ms", 0)), reverse=True)
        return clusters

    DydxClusterDetector.detect_clusters = detect_clusters_fresh
    DydxClusterDetector._fresh_signal_patch_installed = True


install_fresh_signal_patch()


__all__ = [
    "apply_freshness_recovery",
    "effective_cluster_age_ms",
    "freshness_penalty_bps",
    "install_fresh_signal_patch",
]
