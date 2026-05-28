import pytest
from hyper_smart_observer.scoring.wallet_score import WalletScoreEngine
from hyper_smart_observer.app.config import AppConfig
from datetime import datetime, UTC

def test_scoring_reinforced_pnl_concentration():
    config = AppConfig()
    engine = WalletScoreEngine(config)

    # 10 trades, one very large win (90% of total abs pnl)
    pnls = [100.0] + [1.0] * 9

    # We mock _score_rows dependency on DB by calling it with raw rows if we want,
    # but let's just test the private _combine_scores directly for the contract.

    score = engine._combine_scores(
        sample_quality_score=80.0,
        confidence_score=80.0,
        risk_score=80.0,
        consistency_score=80.0,
        recency_score=80.0,
        profit_factor=2.0,
        net_pnl=109.0,
        winrate_confidence=0.8,
        pnl_concentration=0.9 # Very high
    )

    # Should be low due to penalty and capped if it was high
    assert score == 46.0
    assert score <= 65.0

def test_scoring_reinforced_capped_high_concentration():
    config = AppConfig()
    engine = WalletScoreEngine(config)

    # High base scores but high concentration
    score = engine._combine_scores(
        sample_quality_score=95.0,
        confidence_score=95.0,
        risk_score=95.0,
        consistency_score=95.0,
        recency_score=95.0,
        profit_factor=2.0,
        net_pnl=1000.0,
        winrate_confidence=0.9,
        pnl_concentration=0.35 # Just above threshold
    )

    # Base: 95.0 + Boost: 8.0 - Penalty: 14.0 = 89.0
    # Capped at 65.0
    assert score == 65.0

def test_scoring_reinforced_low_concentration():
    config = AppConfig()
    engine = WalletScoreEngine(config)

    score = engine._combine_scores(
        sample_quality_score=80.0,
        confidence_score=80.0,
        risk_score=80.0,
        consistency_score=80.0,
        recency_score=80.0,
        profit_factor=2.0,
        net_pnl=100.0,
        winrate_confidence=0.5,
        pnl_concentration=0.1 # Low
    )

    # (0.3*80) + (0.2*80) + (0.2*80) + (0.15*80) + (0.1*80) + 0 - (0.1*40)
    # 24 + 16 + 16 + 12 + 8 - 4 = 72
    assert score == 72.0
