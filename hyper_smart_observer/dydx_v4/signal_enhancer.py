from __future__ import annotations

import math
import time
from typing import Any


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def signal_quality_points(cluster: Any, now_ms: int | None = None) -> tuple[float, list[str]]:
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    wallet_count = int(getattr(cluster, "wallet_count", 0) or 0)
    total_notional = max(0.0, _num(getattr(cluster, "total_notional_usdc", 0.0)))
    avg_notional = total_notional / max(1, wallet_count)
    age_ms = max(0, int(getattr(cluster, "signal_age_ms", 0) or 0))
    last_ms = int(getattr(cluster, "last_wallet_opened_ms", now) or now)
    last_age_ms = max(0, now - last_ms)
    whale_weight = _clamp(_num(getattr(cluster, "whale_weight", 0.0)), 0.0, 1.0)
    market_priority = _clamp(_num(getattr(cluster, "market_priority", 0.0)), 0.0, 1.0)
    flow_trades = max(0, int(getattr(cluster, "flow_trade_count", 0) or 0))
    origin = str(getattr(cluster, "origin", "rest") or "rest")

    notes: list[str] = []
    score = 0.0
    score += _clamp(wallet_count / 5.0, 0.0, 1.0) * 22.0
    score += _clamp(math.log10(1.0 + total_notional) / 7.0, 0.0, 1.0) * 18.0
    score += _clamp(math.log10(1.0 + avg_notional) / 6.0, 0.0, 1.0) * 14.0
    score += whale_weight * 18.0
    score += market_priority * 8.0
    score += _clamp(flow_trades / 12.0, 0.0, 1.0) * 8.0
    score += _clamp(1.0 - age_ms / 90_000.0, 0.0, 1.0) * 8.0
    score += _clamp(1.0 - last_age_ms / 30_000.0, 0.0, 1.0) * 4.0

    if origin == "stream":
        score += 3.0
        notes.append("stream_origin")
    if getattr(cluster, "freshness_recovered", False):
        score += 2.0
        notes.append("freshness_recovered")
    if wallet_count >= 3:
        notes.append("multi_wallet_consensus")
    if avg_notional >= 50_000:
        notes.append("large_average_notional")
    if whale_weight >= 0.45:
        notes.append("whale_weighted")

    return round(_clamp(score, 0.0, 100.0), 4), notes


def signal_grade(points: float) -> str:
    if points >= 80:
        return "A"
    if points >= 68:
        return "B"
    if points >= 52:
        return "C"
    return "D"


def enhanced_signal_strength(cluster: Any, now_ms: int | None = None) -> tuple[float, float, str, list[str]]:
    points, notes = signal_quality_points(cluster, now_ms=now_ms)
    grade = signal_grade(points)
    base = _clamp(_num(getattr(cluster, "signal_strength", 0.0)), 0.0, 1.0)
    if points >= 80:
        delta = 0.10
    elif points >= 68:
        delta = 0.06
    elif points >= 52:
        delta = 0.02
    elif points < 35:
        delta = -0.08
    else:
        delta = -0.02
    if getattr(cluster, "freshness_recovered", False):
        delta -= 0.015
    boosted = round(_clamp(base + delta, 0.0, 1.0), 6)
    return boosted, points, grade, notes


def apply_signal_enhancement(cluster: Any, now_ms: int | None = None) -> Any:
    strength, points, grade, notes = enhanced_signal_strength(cluster, now_ms=now_ms)
    setattr(cluster, "pre_enhanced_signal_strength", getattr(cluster, "signal_strength", 0.0))
    setattr(cluster, "signal_quality_points", points)
    setattr(cluster, "signal_grade", grade)
    setattr(cluster, "signal_enhancement_notes", notes)
    cluster.signal_strength = strength
    return cluster


def install_signal_enhancer() -> None:
    try:
        from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
    except Exception:
        return
    if getattr(DydxClusterDetector, "_signal_enhancer_installed", False):
        return
    original = DydxClusterDetector.detect_clusters

    def detect_clusters_enhanced(self, *args, **kwargs):
        clusters = list(original(self, *args, **kwargs))
        now_ms = int(time.time() * 1000)
        for cluster in clusters:
            try:
                apply_signal_enhancement(cluster, now_ms=now_ms)
            except Exception:
                continue
        clusters.sort(
            key=lambda c: (
                getattr(c, "signal_quality_points", 0.0),
                getattr(c, "signal_strength", 0.0),
                -getattr(c, "signal_age_ms", 0),
            ),
            reverse=True,
        )
        return clusters

    DydxClusterDetector.detect_clusters = detect_clusters_enhanced
    DydxClusterDetector._signal_enhancer_installed = True


install_signal_enhancer()


__all__ = [
    "apply_signal_enhancement",
    "enhanced_signal_strength",
    "install_signal_enhancer",
    "signal_grade",
    "signal_quality_points",
]
