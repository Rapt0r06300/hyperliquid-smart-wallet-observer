from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from hl_observer.utils.math import clamp


class WalletDiscoveryDecision(StrEnum):
    DISCOVERED = "DISCOVERED"
    SELECT_FOR_BACKFILL = "SELECT_FOR_BACKFILL"
    WATCHLIST = "WATCHLIST"
    REJECT_NO_ADDRESS = "REJECT_NO_ADDRESS"
    REJECT_INVALID_ADDRESS = "REJECT_INVALID_ADDRESS"
    REJECT_TRUNCATED_ADDRESS = "REJECT_TRUNCATED_ADDRESS"
    REJECT_NEGATIVE_PNL = "REJECT_NEGATIVE_PNL"
    REJECT_NEGATIVE_ROI = "REJECT_NEGATIVE_ROI"
    REJECT_INACTIVE = "REJECT_INACTIVE"
    REJECT_TOO_SMALL = "REJECT_TOO_SMALL"
    REJECT_TOO_LARGE_TO_COPY = "REJECT_TOO_LARGE_TO_COPY"
    REJECT_SOURCE_UNRELIABLE = "REJECT_SOURCE_UNRELIABLE"
    REJECT_DUPLICATE = "REJECT_DUPLICATE"
    REJECT_DATA_INCOMPLETE = "REJECT_DATA_INCOMPLETE"
    REJECT_RATE_LIMITED = "REJECT_RATE_LIMITED"
    REJECT_SOURCE_FAILED = "REJECT_SOURCE_FAILED"
    OBSERVE_ONLY = "OBSERVE_ONLY"


class WalletCandidateScore(BaseModel):
    wallet_address: str
    coin: str | None = None
    pnl_positive_score: float = 0.0
    roi_positive_score: float = 0.0
    activity_score: float = 0.0
    recency_score: float = 0.0
    size_score: float = 0.0
    copyability_pre_score: float = 0.0
    source_confidence_score: float = 0.0
    final_discovery_score: float = 0.0
    decision: WalletDiscoveryDecision = WalletDiscoveryDecision.OBSERVE_ONLY
    reasons: list[str] = Field(default_factory=list)


def score_discovery_candidate(
    *,
    wallet_address: str,
    coin: str | None = None,
    source_reliability_score: float,
    external_pnl_usdc: float | None = None,
    external_roi_pct: float | None = None,
    external_volume_usdc: float | None = None,
    external_position_usdc: float | None = None,
    external_win_rate: float | None = None,
    min_discovery_score: float = 55.0,
    require_positive_pnl: bool = True,
    require_positive_roi: bool = False,
    allow_incomplete_external_metrics: bool = True,
) -> WalletCandidateScore:
    reasons: list[str] = []
    pnl_score = 50.0 if external_pnl_usdc is None else clamp(50.0 + external_pnl_usdc / 1000.0 * 50.0, 0.0, 100.0)
    roi_score = 50.0 if external_roi_pct is None else clamp(50.0 + external_roi_pct * 2.0, 0.0, 100.0)
    activity_score = 55.0 if allow_incomplete_external_metrics else 25.0
    recency_score = 55.0 if allow_incomplete_external_metrics else 25.0
    volume = external_volume_usdc if external_volume_usdc is not None else external_position_usdc
    if volume is None:
        size_score = 50.0
        copyability_score = 50.0
        reasons.append("size_unknown")
    else:
        size_score = clamp(volume / 50_000.0 * 100.0, 0.0, 100.0)
        copyability_score = 100.0 - clamp(max(0.0, volume - 2_000_000.0) / 8_000_000.0 * 100.0, 0.0, 100.0)
        if volume < 500:
            reasons.append("wallet_too_small_hint")
        if volume > 5_000_000:
            reasons.append("wallet_too_large_to_copy_hint")
    if external_win_rate is not None:
        activity_score = clamp(external_win_rate * 100.0, 0.0, 100.0)
    source_score = clamp(source_reliability_score * 100.0, 0.0, 100.0)
    final_score = clamp(
        0.25 * pnl_score
        + 0.20 * roi_score
        + 0.15 * activity_score
        + 0.15 * recency_score
        + 0.10 * size_score
        + 0.10 * source_score
        + 0.05 * copyability_score,
        0.0,
        100.0,
    )

    decision = WalletDiscoveryDecision.OBSERVE_ONLY
    if source_reliability_score < 0.35:
        decision = WalletDiscoveryDecision.REJECT_SOURCE_UNRELIABLE
        reasons.append("source_reliability_too_low")
    elif external_pnl_usdc is not None and external_pnl_usdc < 0 and require_positive_pnl:
        decision = WalletDiscoveryDecision.REJECT_NEGATIVE_PNL
        reasons.append("external_pnl_negative")
    elif external_roi_pct is not None and external_roi_pct < 0 and require_positive_roi:
        decision = WalletDiscoveryDecision.REJECT_NEGATIVE_ROI
        reasons.append("external_roi_negative")
    elif external_pnl_usdc is None and require_positive_pnl and not allow_incomplete_external_metrics:
        decision = WalletDiscoveryDecision.REJECT_DATA_INCOMPLETE
        reasons.append("external_pnl_missing")
    elif final_score >= min_discovery_score:
        decision = WalletDiscoveryDecision.SELECT_FOR_BACKFILL
        reasons.append("passes_discovery_score")
    else:
        decision = WalletDiscoveryDecision.OBSERVE_ONLY
        reasons.append("below_min_discovery_score")

    return WalletCandidateScore(
        wallet_address=wallet_address,
        coin=coin.upper() if coin else None,
        pnl_positive_score=pnl_score,
        roi_positive_score=roi_score,
        activity_score=activity_score,
        recency_score=recency_score,
        size_score=size_score,
        copyability_pre_score=copyability_score,
        source_confidence_score=source_score,
        final_discovery_score=final_score,
        decision=decision,
        reasons=reasons,
    )
