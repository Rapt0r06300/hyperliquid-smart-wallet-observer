"""Phase 12: wallet intelligence V2 metrics compute correctly and deny-by-default
on insufficient history (no fabricated leader quality)."""

from __future__ import annotations

from hyper_smart_observer.scoring.pnl_quality import pnl_concentration_score
from hyper_smart_observer.scoring.risk_metrics import calculate_profit_factor
from hyper_smart_observer.scoring.winrate import calculate_winrate
from hyper_smart_observer.scoring.wallet_score import build_wallet_score


def test_core_v2_metrics_are_correct():
    assert calculate_winrate([1.0, -1.0, 2.0, -1.0]) == 0.5
    assert calculate_profit_factor(gross_profit=30.0, gross_loss=10.0) == 3.0
    # pnl_concentration_score is a diffuseness/quality score: higher = healthier.
    # One big win dominating -> LOW score; evenly spread pnl -> HIGH score.
    one_big_win = pnl_concentration_score([100.0, 1.0, 1.0, 1.0])
    diffuse = pnl_concentration_score([10.0, 10.0, 10.0, 10.0])
    assert one_big_win < diffuse


def test_insufficient_history_not_a_reliable_leader():
    score = build_wallet_score("0x" + "a" * 40, [1.0])
    status = getattr(score, "status", None)
    assert status is None or str(status).upper() != "SCORED" or getattr(score, "confidence_score", 0.0) <= 50.0
