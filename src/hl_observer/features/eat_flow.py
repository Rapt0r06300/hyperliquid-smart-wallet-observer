"""V13 #154 — eat-flow (polyrec): how much aggressive volume 'eats' through book depth."""

from __future__ import annotations


def eat_flow_ratio(aggressive_volume_usd: float, top_depth_usd: float) -> float:
    """>1 means incoming flow exceeded the visible top-level depth (book is being eaten)."""
    d = max(1e-9, float(top_depth_usd))
    return round(max(0.0, float(aggressive_volume_usd)) / d, 6)


def levels_eaten(aggressive_volume_usd: float, level_depths_usd: list[float]) -> int:
    """How many book levels the aggressive volume would clear."""
    remaining = max(0.0, float(aggressive_volume_usd))
    eaten = 0
    for d in level_depths_usd or []:
        d = max(0.0, float(d))
        if remaining <= 0.0:
            break
        if remaining >= d:
            eaten += 1
            remaining -= d
        else:
            break
    return eaten


__all__ = ["eat_flow_ratio", "levels_eaten"]
