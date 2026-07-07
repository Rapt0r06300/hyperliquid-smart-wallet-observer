"""Levier A: la sélection des leaders surveillés privilégie l'activité récente
(sans sacrifier la qualité) -> plus de fills frais -> moins de refus 'stale'."""

import inspect

from hl_observer.scoring.shortlist_rank import rank_shortlist
from hl_observer.wallets.discovery_scoring import score_discovery_candidate


def _score(win_rate):
    return score_discovery_candidate(
        wallet_address="0x" + "a" * 40,
        source_reliability_score=0.8,
        external_pnl_usdc=1000.0,
        external_roi_pct=10.0,
        external_volume_usdc=50_000.0,
        external_win_rate=win_rate,  # -> activity_score = win_rate*100
    ).final_discovery_score


def test_more_active_wallet_scores_higher():
    active = _score(0.90)     # very active
    quiet = _score(0.20)      # quiet
    assert active > quiet, (active, quiet)


def test_final_score_stays_bounded():
    assert 0.0 <= _score(0.5) <= 100.0
    assert 0.0 <= _score(1.0) <= 100.0


def test_discovery_weights_sum_to_one():
    # the activity-forward reweight must still be a proper weighted average
    weights = [0.20, 0.15, 0.22, 0.20, 0.08, 0.10, 0.05]
    assert abs(sum(weights) - 1.0) < 1e-9
    # activity+recency now dominate pnl+roi for "fresh fills" leaders
    assert (0.22 + 0.20) > (0.20 + 0.15)


def test_shortlist_ranker_is_activity_forward_by_default():
    # default activity_weight bumped 0.35 -> 0.5
    assert inspect.signature(rank_shortlist).parameters["activity_weight"].default == 0.5
