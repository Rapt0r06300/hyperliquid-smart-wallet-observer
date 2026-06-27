from __future__ import annotations

import math

SOFT_TAIL_START_MS = 30_000
SOFT_TAIL_END_MS = 90_000
SOFT_TAIL_HALF_LIFE_MS = 18_000
MIN_LATE_FRESHNESS = 0.035


def soft_late_freshness_score(signal_age_ms: int) -> float:
    if signal_age_ms <= 0:
        return 1.0
    if signal_age_ms < SOFT_TAIL_START_MS:
        return math.pow(0.5, signal_age_ms / 12_000)
    if signal_age_ms >= SOFT_TAIL_END_MS:
        return 0.0
    base_at_tail = math.pow(0.5, SOFT_TAIL_START_MS / 12_000)
    tail_age = signal_age_ms - SOFT_TAIL_START_MS
    score = base_at_tail * math.pow(0.5, tail_age / SOFT_TAIL_HALF_LIFE_MS)
    return max(MIN_LATE_FRESHNESS, score)


def install_edge_freshness_patch() -> None:
    try:
        import hyper_smart_observer.dydx_v4.edge_calculator as ec
    except Exception:
        return
    if getattr(ec, "_soft_late_freshness_installed", False):
        return
    ec.signal_freshness_score = soft_late_freshness_score
    ec.MAX_SIGNAL_AGE_MS = SOFT_TAIL_END_MS
    ec._soft_late_freshness_installed = True


install_edge_freshness_patch()


__all__ = ["install_edge_freshness_patch", "soft_late_freshness_score"]
