from __future__ import annotations


def entry_edge_score(*, expectancy: float | None, copy_delay_bps: float = 0.0) -> float:
    if expectancy is None:
        return 0.0
    return max(0.0, min(100.0, expectancy - copy_delay_bps))
