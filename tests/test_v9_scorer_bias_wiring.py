"""Confirms the multi-TF directional bias is wired into the live scorer and is
bounded, additive, and neutral by default (paper-only)."""

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.edge.bias_model import bias_from_closes
from hl_observer.features.direction import multi_tf_direction


def _input(**over):
    base = dict(
        action_type="ADD",
        direction="LONG",
        leader_expected_edge_bps=60.0,
        leader_consistency_factor=1.0,
        signal_age_ms=2000,
        consensus_wallets=3,
        liquidity_score=0.9,
        leader_score=80.0,
        leader_reference_price=100.0,
        current_mid=100.0,
        leader_notional_usdt=50.0,
        current_open_exposure_usdt=0.0,
        current_open_positions=0,
        max_open_positions=6,
    )
    base.update(over)
    return RealtimeCopyScoreInput(**base)


_CFG = RealtimeCopyRiskConfig(min_edge_required_bps=10.0, max_signal_age_ms=30_000, max_copy_degradation_bps=40.0)


def test_default_bias_is_neutral():
    s0 = score_realtime_copy_candidate(_input(), config=_CFG)
    sb = score_realtime_copy_candidate(_input(directional_bias_bps=0.0), config=_CFG)
    assert s0.edge_remaining_bps == sb.edge_remaining_bps


def test_positive_bias_raises_edge_negative_lowers():
    neg = score_realtime_copy_candidate(_input(directional_bias_bps=-8.0), config=_CFG)
    zero = score_realtime_copy_candidate(_input(directional_bias_bps=0.0), config=_CFG)
    pos = score_realtime_copy_candidate(_input(directional_bias_bps=8.0), config=_CFG)
    assert neg.edge_remaining_bps < zero.edge_remaining_bps < pos.edge_remaining_bps
    # additive and exact (bias not multiplied by freshness)
    assert round(pos.edge_remaining_bps - zero.edge_remaining_bps, 6) == 8.0


def test_bias_is_bounded_in_scorer():
    huge = score_realtime_copy_candidate(_input(directional_bias_bps=10_000.0), config=_CFG)
    bounded = score_realtime_copy_candidate(_input(directional_bias_bps=10.0), config=_CFG)
    assert huge.edge_remaining_bps == bounded.edge_remaining_bps  # clamped at +10


def test_end_to_end_trend_aligned_bias_helps():
    # A real uptrend -> LONG gets a positive bias from the bias model.
    up = [float(i) for i in range(1, 60)]
    mtf = multi_tf_direction(up, up)
    bias = bias_from_closes(direction_side="LONG", closes_fast_tf=up, closes_slow_tf=up)
    assert bias.bias_bps > 0 and mtf.combined == "UP"
    aligned = score_realtime_copy_candidate(_input(directional_bias_bps=bias.bias_bps), config=_CFG)
    neutral = score_realtime_copy_candidate(_input(directional_bias_bps=0.0), config=_CFG)
    assert aligned.edge_remaining_bps > neutral.edge_remaining_bps
