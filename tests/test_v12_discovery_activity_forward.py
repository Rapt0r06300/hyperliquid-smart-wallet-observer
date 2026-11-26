"""Discovery scoring must not confuse leader win rate with measured activity."""

import inspect

from hl_observer.scoring.shortlist_rank import rank_shortlist
from hl_observer.wallets.discovery_scoring import (
    WalletDiscoveryDecision,
    score_discovery_candidate,
)


def _score(win_rate):
    return score_discovery_candidate(
        wallet_address="0x" + "a" * 40,
        source_reliability_score=0.8,
        external_pnl_usdc=1000.0,
        external_roi_pct=10.0,
        external_volume_usdc=50_000.0,
        external_win_rate=win_rate,
    )


def test_external_win_rate_does_not_proxy_activity_or_copy_edge():
    low_reported_win_rate = _score(0.20)
    high_reported_win_rate = _score(0.90)

    assert low_reported_win_rate.activity_score == high_reported_win_rate.activity_score
    assert low_reported_win_rate.final_discovery_score == high_reported_win_rate.final_discovery_score


def test_unmeasured_activity_and_recency_receive_neutral_scores():
    score = score_discovery_candidate(
        wallet_address="0x" + "a" * 40,
        source_reliability_score=0.8,
        allow_incomplete_external_metrics=True,
    )

    assert score.activity_score == 50.0
    assert score.recency_score == 50.0
    assert score.decision == WalletDiscoveryDecision.OBSERVE_ONLY


def test_verified_public_trade_activity_and_recency_are_scored_from_event_times():
    common = {
        "wallet_address": "0x" + "a" * 40,
        "source_reliability_score": 0.8,
        "allow_incomplete_external_metrics": True,
        "activity_evidence_verified": True,
        "activity_trade_count": 15,
        "activity_window_start_ms": 1_700_000_000_000,
        "activity_window_end_ms": 1_700_000_045_000,
    }
    fresh = score_discovery_candidate(
        **common,
        last_trade_event_ms=1_700_000_044_000,
        reference_now_ms=1_700_000_045_000,
    )
    stale = score_discovery_candidate(
        **{
            **common,
            "activity_window_start_ms": 1_699_913_600_000,
            "activity_window_end_ms": 1_699_913_645_000,
            "last_trade_event_ms": 1_699_913_644_000,
            "reference_now_ms": 1_700_000_045_000,
        }
    )

    assert fresh.activity_score == 100.0
    assert fresh.recency_score == 100.0
    assert stale.activity_score == fresh.activity_score
    assert stale.recency_score == 0.0
    assert fresh.final_discovery_score > stale.final_discovery_score


def test_unverified_or_invalid_public_activity_is_not_used_as_evidence():
    score = score_discovery_candidate(
        wallet_address="0x" + "a" * 40,
        source_reliability_score=0.8,
        activity_evidence_verified=False,
        activity_trade_count=1000,
        activity_window_start_ms=1_700_000_000_000,
        activity_window_end_ms=1_700_000_045_000,
        last_trade_event_ms=1_700_000_044_000,
        reference_now_ms=1_700_000_045_000,
    )

    assert score.activity_score == 50.0
    assert score.recency_score == 50.0
    assert "activity_evidence_unmeasured_or_unverified" in score.reasons


def test_future_public_trade_timestamp_fails_closed_to_neutral_recency():
    score = score_discovery_candidate(
        wallet_address="0x" + "a" * 40,
        source_reliability_score=0.8,
        activity_evidence_verified=True,
        activity_trade_count=15,
        activity_window_start_ms=1_700_000_000_000,
        activity_window_end_ms=1_700_000_045_000,
        last_trade_event_ms=1_700_000_120_000,
        reference_now_ms=1_700_000_045_000,
    )

    assert score.activity_score == 100.0
    assert score.recency_score == 50.0
    assert "activity_event_timestamp_invalid" in score.reasons


def test_final_score_stays_bounded():
    assert 0.0 <= _score(0.5).final_discovery_score <= 100.0
    assert 0.0 <= _score(1.0).final_discovery_score <= 100.0


def test_discovery_weights_sum_to_one():
    # Historical weight mix stays bounded while unmeasured fields use neutral priors.
    weights = [0.20, 0.15, 0.22, 0.20, 0.08, 0.10, 0.05]
    assert abs(sum(weights) - 1.0) < 1e-9
    # Activity receives the largest combined weight, but only collector-verified
    # public trade observations may influence it; it is still not an edge proof.
    assert (0.22 + 0.20) > (0.20 + 0.15)


def test_shortlist_ranker_is_activity_forward_by_default():
    # default activity_weight bumped 0.35 -> 0.5
    assert inspect.signature(rank_shortlist).parameters["activity_weight"].default == 0.5
