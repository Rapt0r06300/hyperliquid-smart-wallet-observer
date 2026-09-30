"""V14 #177 — Proxy pool health, rotation + fallback (read-only summary for dashboard).

Pure policy on top of the existing proxy_pool: scores each proxy by success rate + latency,
rotates among healthy ones, and falls back (DIRECT) when none are healthy. No network here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ProxyStat:
    proxy_id: str
    ok: int = 0
    fail: int = 0
    last_latency_ms: float | None = None
    banned: bool = False


@dataclass(frozen=True, slots=True)
class ProxyHealth:
    proxy_id: str
    success_rate: float
    samples: int
    last_latency_ms: float | None
    healthy: bool
    banned: bool


def proxy_health(stat: ProxyStat, *, min_success_rate: float = 0.7, min_samples: int = 5) -> ProxyHealth:
    samples = int(stat.ok) + int(stat.fail)
    rate = (stat.ok / samples) if samples > 0 else 0.0
    healthy = (not stat.banned) and (samples < min_samples or rate >= min_success_rate)
    return ProxyHealth(
        proxy_id=stat.proxy_id,
        success_rate=round(rate, 6),
        samples=samples,
        last_latency_ms=stat.last_latency_ms,
        healthy=bool(healthy),
        banned=bool(stat.banned),
    )


@dataclass(frozen=True, slots=True)
class ProxyPoolSummary:
    total: int
    healthy: int
    banned: int
    next_proxy_id: str | None    # None => fall back to DIRECT
    fallback: str                # "PROXY" | "DIRECT"
    health: tuple[ProxyHealth, ...]


def summarize_proxy_pool(
    stats: Sequence[ProxyStat],
    *,
    min_success_rate: float = 0.7,
    rotation_index: int = 0,
) -> ProxyPoolSummary:
    healths = [proxy_health(s, min_success_rate=min_success_rate) for s in stats]
    healthy = [h for h in healths if h.healthy]
    # rotate among healthy, preferring higher success then lower latency
    healthy_sorted = sorted(healthy, key=lambda h: (-h.success_rate, (h.last_latency_ms if h.last_latency_ms is not None else 1e9)))
    next_id = None
    fallback = "DIRECT"
    if healthy_sorted:
        next_id = healthy_sorted[rotation_index % len(healthy_sorted)].proxy_id
        fallback = "PROXY"
    return ProxyPoolSummary(
        total=len(healths),
        healthy=len(healthy),
        banned=sum(1 for h in healths if h.banned),
        next_proxy_id=next_id,
        fallback=fallback,
        health=tuple(healths),
    )


__all__ = ["ProxyStat", "ProxyHealth", "proxy_health", "ProxyPoolSummary", "summarize_proxy_pool"]
