from __future__ import annotations

import math
from typing import Any


def cluster_whale_weight(cluster: Any) -> float:
    total = max(0.0, float(getattr(cluster, "total_notional_usdc", 0.0) or 0.0))
    wallets = max(1, int(getattr(cluster, "wallet_count", 1) or 1))
    avg = total / wallets
    avg_score = min(1.0, math.log10(1.0 + avg) / 6.0)
    total_score = min(1.0, math.log10(1.0 + total) / 7.0)
    return round(0.70 * avg_score + 0.30 * total_score, 6)


def boosted_signal_strength(cluster: Any) -> float:
    base = max(0.0, min(1.0, float(getattr(cluster, "signal_strength", 0.0) or 0.0)))
    weight = cluster_whale_weight(cluster)
    fresh_bonus = 0.03 if bool(getattr(cluster, "is_fresh", False)) else 0.0
    return round(min(1.0, base + weight * 0.18 + fresh_bonus), 6)


def install_cluster_whale_weight_patch() -> None:
    try:
        from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
    except Exception:
        return
    if getattr(DydxClusterDetector, "_whale_weight_patch_installed", False):
        return
    original = DydxClusterDetector.detect_clusters

    def detect_clusters_weighted(self, *args, **kwargs):
        clusters = list(original(self, *args, **kwargs))
        for cluster in clusters:
            try:
                weight = cluster_whale_weight(cluster)
                setattr(cluster, "whale_weight", weight)
                setattr(cluster, "pre_whale_signal_strength", getattr(cluster, "signal_strength", 0.0))
                cluster.signal_strength = boosted_signal_strength(cluster)
            except Exception:
                continue
        clusters.sort(key=lambda c: (getattr(c, "signal_strength", 0.0), getattr(c, "whale_weight", 0.0)), reverse=True)
        return clusters

    DydxClusterDetector.detect_clusters = detect_clusters_weighted
    DydxClusterDetector._whale_weight_patch_installed = True


install_cluster_whale_weight_patch()


__all__ = ["boosted_signal_strength", "cluster_whale_weight", "install_cluster_whale_weight_patch"]
