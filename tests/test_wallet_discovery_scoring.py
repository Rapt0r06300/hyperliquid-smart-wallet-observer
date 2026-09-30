from hl_observer.wallets.discovery_scoring import (
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
