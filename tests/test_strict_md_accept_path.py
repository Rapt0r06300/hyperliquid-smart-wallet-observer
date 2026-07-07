"""Proof that the STRICT MD thresholds (6000ms / 35bps / 12bps / 0.5) still ACCEPT
a genuinely clean real signal — so the flat equity is 'no clean signal yet', not a
broken gate. Pure function, no network. Read-only, simulation-only.
"""

from __future__ import annotations

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)

# Exactly the launcher / MD thresholds.
STRICT_MD = RealtimeCopyRiskConfig(
    min_edge_required_bps=35.0,
    max_signal_age_ms=6000,
    max_copy_degradation_bps=12.0,
    min_liquidity_score=0.5,
)


def _signal(**over):
    base = dict(
        action_type="OPEN_LONG", direction="LONG",
        leader_expected_edge_bps=120.0, leader_consistency_factor=1.0,
        signal_age_ms=200, consensus_wallets=3, liquidity_score=0.95,
        leader_score=90.0, leader_reference_price=100.0, current_mid=100.0,
        leader_notional_usdt=50.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=5,
    )
    base.update(over)
    return RealtimeCopyScoreInput(**base)


def test_clean_signal_is_accepted_under_strict_md():
    score = score_realtime_copy_candidate(_signal(), config=STRICT_MD)
    assert score.accepted is True, f"clean signal rejected: {score.refusal_reasons}"
    assert score.decision == "ACCEPT_LOCAL_SIMULATION"
    assert score.edge_remaining_bps >= 35.0
    assert score.copy_degradation_bps <= 12.0


def test_stale_signal_rejected_exactly_like_dashboard():
    score = score_realtime_copy_candidate(_signal(signal_age_ms=10_000), config=STRICT_MD)
    assert score.accepted is False
    assert "STALE_SIGNAL" in score.refusal_reasons


def test_low_edge_rejected_like_dashboard():
    score = score_realtime_copy_candidate(_signal(leader_expected_edge_bps=10.0), config=STRICT_MD)
    assert score.accepted is False
    assert "EDGE_REMAINING_TOO_LOW" in score.refusal_reasons


def test_illiquid_rejected_like_dashboard():
    score = score_realtime_copy_candidate(_signal(liquidity_score=0.1), config=STRICT_MD)
    assert score.accepted is False
    assert "LIQUIDITY_TOO_LOW" in score.refusal_reasons
