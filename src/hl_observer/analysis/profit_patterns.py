from __future__ import annotations

from typing import TYPE_CHECKING

from hl_observer.utils.math import clamp

if TYPE_CHECKING:
    from hl_observer.analysis.opening_patterns import OpeningPatternStats


def compute_profit_pattern_score(
    *,
    expectancy: float | None,
    profit_factor: float | None,
    wilson_lower_bound: float | None,
    sample_size: int,
    min_samples: int,
) -> float:
    """Return the canonical bounded score used for opening-profit patterns.

    Pure/read-only helper: it centralizes the score used by the live analysis
    path and by ranking, without any execution or venue I/O.
    """

    return clamp(
        0.20 * clamp((expectancy or 0) / 100.0 * 100.0, 0.0, 100.0)
        + 0.18 * clamp((profit_factor or 0) / 3.0 * 100.0, 0.0, 100.0)
        + 0.15 * clamp((wilson_lower_bound or 0) * 100.0, 0.0, 100.0)
        + 0.12 * clamp(sample_size / min_samples * 100.0, 0.0, 100.0)
        + 0.35 * 50.0,
        0.0,
        100.0,
    )


def rank_profit_patterns(
    pnls_by_type: dict[str, list[float]],
    *,
    min_samples: int = 20,
) -> list[OpeningPatternStats]:
    # Local import keeps the scoring helper usable by opening_patterns itself
    # without creating an import cycle.
    from hl_observer.analysis.opening_patterns import compute_opening_pattern_stats

    stats = [
        compute_opening_pattern_stats(pnls, opening_type=opening_type, min_samples=min_samples)
        for opening_type, pnls in pnls_by_type.items()
    ]
    return sorted(stats, key=lambda item: item.score, reverse=True)
