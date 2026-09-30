from __future__ import annotations


def calculate_confidence(sample_size: int, *, min_samples: int = 30) -> float:
    if sample_size <= 0:
        return 0.0
    return min(1.0, sample_size / max(1, min_samples))


def calculate_confidence_score(
    *,
    sample_quality_score: float,
    recency_score: float,
    closed_pnl_points: int,
    min_closed_pnl_points: int,
) -> float:
    pnl_coverage = calculate_confidence(closed_pnl_points, min_samples=min_closed_pnl_points) * 100.0
    return max(
        0.0,
        min(
            100.0,
            (0.55 * sample_quality_score) + (0.25 * pnl_coverage) + (0.20 * recency_score),
        ),
    )
