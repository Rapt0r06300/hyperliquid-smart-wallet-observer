from __future__ import annotations

from hl_observer.analysis.opening_patterns import OpeningPatternStats, compute_opening_pattern_stats


def rank_profit_patterns(pnls_by_type: dict[str, list[float]], *, min_samples: int = 20) -> list[OpeningPatternStats]:
    stats = [
        compute_opening_pattern_stats(pnls, opening_type=opening_type, min_samples=min_samples)
        for opening_type, pnls in pnls_by_type.items()
    ]
    return sorted(stats, key=lambda item: item.score, reverse=True)
