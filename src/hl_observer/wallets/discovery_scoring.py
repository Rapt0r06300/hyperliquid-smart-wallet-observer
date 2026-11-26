from __future__ import annotations

from math import isfinite

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, Field

from hl_observer.utils.math import clamp
from hl_observer.utils.time import now_ms

PUBLIC_TRADE_ACTIVITY_SATURATION_PER_45S = 15.0
PUBLIC_TRADE_RECENCY_FRESH_MS = 5 * 60_000
PUBLIC_TRADE_RECENCY_STALE_MS = 24 * 60 * 60_000
PUBLIC_TRADE_CLOCK_SKEW_TOLERANCE_MS = 60_000


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
    activity_evidence_verified: bool = False,
    activity_trade_count: int | None = None,
    activity_window_start_ms: int | None = None,
    activity_window_end_ms: int | None = None,
    last_trade_event_ms: int | None = None,
    reference_now_ms: int | None = None,
    min_discovery_score: float = 55.0,
    require_positive_pnl: bool = True,
    require_positive_roi: bool = False,
    allow_incomplete_external_metrics: bool = True,
) -> WalletCandidateScore:
    reasons: list[str] = []
    pnl_score = 50.0 if external_pnl_usdc is None else clamp(50.0 + external_pnl_usdc / 1000.0 * 50.0, 0.0, 100.0)
    roi_score = 50.0 if external_roi_pct is None else clamp(50.0 + external_roi_pct * 2.0, 0.0, 100.0)
    # Public trade observations are discovery triage only. They establish neither
    # trade direction nor follower-realizable performance, and are only trusted
    # when the collector explicitly verifies exchange timestamps and scan bounds.
    activity_score = 50.0 if allow_incomplete_external_metrics else 25.0
    recency_score = 50.0 if allow_incomplete_external_metrics else 25.0
    activity_values = (activity_trade_count, activity_window_start_ms, activity_window_end_ms, last_trade_event_ms)
    activity_types_valid = (
        isinstance(activity_trade_count, int)
        and not isinstance(activity_trade_count, bool)
        and activity_trade_count >= 0
        and all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in activity_values[1:])
    )
    activity_window_ms = (
        activity_window_end_ms - activity_window_start_ms
        if activity_types_valid and activity_window_start_ms is not None and activity_window_end_ms is not None
        else 0
    )
    if activity_evidence_verified is True and activity_types_valid and 0 < activity_window_ms <= 300_000:
        event_inside_window = (
            activity_window_start_ms - PUBLIC_TRADE_CLOCK_SKEW_TOLERANCE_MS
            <= last_trade_event_ms
            <= activity_window_end_ms + PUBLIC_TRADE_CLOCK_SKEW_TOLERANCE_MS
        )
        activity_score = clamp(
            activity_trade_count * 45_000.0 / activity_window_ms / PUBLIC_TRADE_ACTIVITY_SATURATION_PER_45S * 100.0,
            0.0,
            100.0,
        )
        effective_now_ms = now_ms() if reference_now_ms is None else reference_now_ms
        valid_reference = isinstance(effective_now_ms, int) and not isinstance(effective_now_ms, bool) and effective_now_ms > 0
        age_ms = effective_now_ms - last_trade_event_ms if valid_reference else -1
        if event_inside_window and valid_reference and age_ms >= -PUBLIC_TRADE_CLOCK_SKEW_TOLERANCE_MS:
            age_ms = max(0, age_ms)
            recency_score = clamp(
                (PUBLIC_TRADE_RECENCY_STALE_MS - age_ms)
                / (PUBLIC_TRADE_RECENCY_STALE_MS - PUBLIC_TRADE_RECENCY_FRESH_MS)
                * 100.0,
                0.0,
                100.0,
            )
            reasons.append("public_trade_activity_rate_measured_for_backfill_triage")
            reasons.append("exchange_event_recency_measured_not_edge_proof")
        else:
            reasons.append("activity_event_timestamp_invalid")
            if allow_incomplete_external_metrics:
                recency_score = 50.0
    else:
        reasons.append("activity_evidence_unmeasured_or_unverified")
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
        # A reported win rate is neither trade activity nor copyable net edge:
        # it lacks a sample-size guarantee and ignores loss size, fees, funding,
        # spread, slippage, and follower execution delay. Keep it informational
        # on the candidate record; never let it rank a wallet for backfill.
        reasons.append("reported_win_rate_not_used_as_activity_or_copy_edge")
    source_score = clamp(source_reliability_score * 100.0, 0.0, 100.0)
    # Historical activity-forward weights are retained, but this API currently
    # has no measured trade-count or trade-age inputs. Their scores therefore
    # remain neutral (or penalized when incomplete data are disallowed); this
    # ranking is not evidence of freshness or follower profitability.
    final_score = clamp(
        0.20 * pnl_score
        + 0.15 * roi_score
        + 0.22 * activity_score
        + 0.20 * recency_score
        + 0.08 * size_score
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


def short_history_receipt(
    *,
    trades_count: int,
    estimated_score: float,
    min_trades: int = 30,
) -> dict[str, object]:
    """Prevent one lucky trade from receiving full-confidence discovery weight."""
    if isinstance(trades_count, bool) or not isinstance(trades_count, int) or trades_count < 0:
        return {"status": "UNMEASURABLE", "reason": "trades_count_must_be_non_negative_integer"}
    if isinstance(min_trades, bool) or not isinstance(min_trades, int) or min_trades <= 0:
        return {"status": "UNMEASURABLE", "reason": "min_trades_must_be_positive_integer"}
    if isinstance(estimated_score, bool) or not isinstance(estimated_score, (int, float)) or not isfinite(float(estimated_score)):
        return {"status": "UNMEASURABLE", "reason": "estimated_score_must_be_finite"}
    confidence = min(1.0, trades_count / min_trades)
    adjusted_score = float(estimated_score) * confidence
    known = trades_count >= min_trades
    return {
        "status": "PROVEN" if known else "MORE_DATA",
        "trades_count": trades_count,
        "min_trades": min_trades,
        "confidence": round(confidence, 8),
        "estimated_score": float(estimated_score),
        "adjusted_score": round(adjusted_score, 8),
        "score_known": known,
        "reason": "minimum_history_met" if known else "history_too_short",
    }
