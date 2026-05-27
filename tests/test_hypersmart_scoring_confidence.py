from datetime import UTC, datetime, timedelta

from hyper_smart_observer.scoring.confidence import calculate_confidence, calculate_confidence_score
from hyper_smart_observer.scoring.sample_quality import (
    calculate_consistency_score,
    calculate_history_days,
    calculate_recency_score,
    calculate_sample_quality_score,
)


def test_hypersmart_confidence_ratio():
    assert calculate_confidence(15, min_samples=30) == 0.5


def test_hypersmart_sample_quality_insufficient_if_too_few_fills():
    score = calculate_sample_quality_score(
        usable_fills=5,
        skipped_fills=0,
        closed_pnl_points=5,
        history_days=10,
        min_fills=30,
        min_closed_pnl_points=10,
        min_history_days=7,
    )

    assert score < 60


def test_hypersmart_sample_quality_insufficient_if_history_too_short():
    score = calculate_sample_quality_score(
        usable_fills=30,
        skipped_fills=0,
        closed_pnl_points=10,
        history_days=1,
        min_fills=30,
        min_closed_pnl_points=10,
        min_history_days=7,
    )

    assert score < 100


def test_hypersmart_recency_and_history_days():
    now = datetime.now(UTC)
    assert calculate_history_days(now - timedelta(days=7), now) == 7
    assert calculate_recency_score(now, half_life_days=14, now=now) == 100


def test_hypersmart_confidence_score_is_bounded():
    score = calculate_confidence_score(
        sample_quality_score=100,
        recency_score=100,
        closed_pnl_points=10,
        min_closed_pnl_points=10,
    )

    assert score == 100


def test_hypersmart_consistency_penalizes_single_big_win():
    concentrated = calculate_consistency_score([100.0, -1.0, 1.0], max_drawdown=1.0)
    smoother = calculate_consistency_score([4.0, -1.0, 3.0, -1.0], max_drawdown=1.0)

    assert smoother > concentrated
