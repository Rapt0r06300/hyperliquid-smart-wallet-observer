from hl_observer.wallets.discovery_scoring import (
    PUBLIC_TRADE_RECENCY_STALE_MS,
    WalletDiscoveryDecision,
    score_discovery_candidate,
)

VALID_WALLET = "0x" + "6" * 40


def test_discovery_scores_positive_pnl_higher():
    positive = score_discovery_candidate(
        wallet_address=VALID_WALLET,
        source_reliability_score=0.8,
        external_pnl_usdc=10_000,
        require_positive_pnl=True,
    )
    missing = score_discovery_candidate(
        wallet_address=VALID_WALLET,
        source_reliability_score=0.8,
        external_pnl_usdc=None,
        require_positive_pnl=True,
    )

    assert positive.pnl_positive_score > missing.pnl_positive_score
    assert positive.final_discovery_score > missing.final_discovery_score


def test_discovery_scores_positive_roi_higher():
    positive = score_discovery_candidate(
        wallet_address=VALID_WALLET,
        source_reliability_score=0.8,
        external_roi_pct=20,
        require_positive_pnl=False,
    )
    negative = score_discovery_candidate(
        wallet_address=VALID_WALLET,
        source_reliability_score=0.8,
        external_roi_pct=-20,
        require_positive_pnl=False,
    )

    assert positive.roi_positive_score > negative.roi_positive_score


def test_discovery_rejects_negative_pnl_when_required():
    score = score_discovery_candidate(
        wallet_address=VALID_WALLET,
        source_reliability_score=0.8,
        external_pnl_usdc=-1,
        require_positive_pnl=True,
    )

    assert score.decision == WalletDiscoveryDecision.REJECT_NEGATIVE_PNL


def test_discovery_does_not_reject_missing_roi_when_allowed():
    score = score_discovery_candidate(
        wallet_address=VALID_WALLET,
        source_reliability_score=0.8,
        external_pnl_usdc=100,
        external_roi_pct=None,
        require_positive_roi=False,
    )

    assert score.decision != WalletDiscoveryDecision.REJECT_NEGATIVE_ROI


def test_stale_public_trade_activity_cannot_keep_backfill_priority():
    now_ms = 1_800_000_000_000
    window_end_ms = now_ms - PUBLIC_TRADE_RECENCY_STALE_MS
    score = score_discovery_candidate(
        wallet_address=VALID_WALLET,
        source_reliability_score=0.85,
        activity_evidence_verified=True,
        activity_trade_count=100,
        activity_window_start_ms=window_end_ms - 45_000,
        activity_window_end_ms=window_end_ms,
        last_trade_event_ms=window_end_ms,
        reference_now_ms=now_ms,
        require_positive_pnl=False,
    )

    assert score.activity_score == 0.0
    assert score.recency_score == 0.0
    assert score.decision != WalletDiscoveryDecision.SELECT_FOR_BACKFILL
    assert "public_trade_activity_stale_at_or_beyond_admission_window" in score.reasons
