from __future__ import annotations

from hl_observer.edge.signal_decay import decay_edge


def latency_decay_bps(raw_edge_bps: float, latency_ms: int, half_life_ms: int) -> float:
    return raw_edge_bps - decay_edge(raw_edge_bps, latency_ms, half_life_ms)
