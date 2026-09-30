from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc

from hyper_smart_observer.hyperliquid_client.models import ScoreBreakdown, WalletScoreStatus
from hyper_smart_observer.scoring.smart_wallet_ranking import SmartWalletRankingEngine


def test_ranking_refuses_small_or_unscored_sample():
    score = ScoreBreakdown(
        wallet_address="0x" + "a" * 40,
        calculated_at=datetime.now(UTC),
        status=WalletScoreStatus.INSUFFICIENT_DATA,
        total_fills=2,
        usable_fills=2,
        skipped_fills=0,
    )

    ranking = SmartWalletRankingEngine().rank_score(score)

    assert ranking.status == "REJECTED"
    assert ranking.rank_score == 0.0


def test_ranking_marks_valid_score_research_only():
    score = ScoreBreakdown(
        wallet_address="0x" + "b" * 40,
        calculated_at=datetime.now(UTC),
        status=WalletScoreStatus.SCORED,
        total_fills=40,
        usable_fills=40,
        skipped_fills=0,
        sample_quality_score=90,
        confidence_score=90,
        risk_score=80,
        consistency_score=70,
        recency_score=60,
    )

    ranking = SmartWalletRankingEngine().rank_score(score)

    assert ranking.status == "RESEARCH_OBSERVATION"
    assert "research" in ranking.reason
