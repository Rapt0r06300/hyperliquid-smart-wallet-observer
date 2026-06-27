from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass

from pydantic import BaseModel, Field


class FollowMode(StrEnum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    PAPER_FOLLOW = "PAPER_FOLLOW"
    TESTNET_FOLLOW_LOCKED = "TESTNET_FOLLOW_LOCKED"
    TESTNET_FOLLOW_ALLOWED = "TESTNET_FOLLOW_ALLOWED"
    LIVE_DISABLED_ALWAYS = "LIVE_DISABLED_ALWAYS"


class FollowDecisionKind(StrEnum):
    IGNORE = "IGNORE"
    OBSERVE = "OBSERVE"
    PAPER_FOLLOW_ALLOWED = "PAPER_FOLLOW_ALLOWED"
    PAPER_FOLLOW_REJECTED = "PAPER_FOLLOW_REJECTED"
    TESTNET_CANDIDATE_LOCKED = "TESTNET_CANDIDATE_LOCKED"
    REJECT_TOO_LATE = "REJECT_TOO_LATE"
    REJECT_PRICE_MOVED = "REJECT_PRICE_MOVED"
    REJECT_TOO_ILLIQUID = "REJECT_TOO_ILLIQUID"
    REJECT_SPREAD_TOO_WIDE = "REJECT_SPREAD_TOO_WIDE"
    REJECT_SLIPPAGE_TOO_HIGH = "REJECT_SLIPPAGE_TOO_HIGH"
    REJECT_WALLET_SCORE_LOW = "REJECT_WALLET_SCORE_LOW"
    REJECT_PATTERN_SCORE_LOW = "REJECT_PATTERN_SCORE_LOW"
    REJECT_RISK_FILTER = "REJECT_RISK_FILTER"
    REJECT_MARKET_REGIME = "REJECT_MARKET_REGIME"
    REJECT_DATA_STALE = "REJECT_DATA_STALE"
    REJECT_WALLET_REDUCING = "REJECT_WALLET_REDUCING"
    REJECT_WALLET_CLOSING = "REJECT_WALLET_CLOSING"
    REJECT_POSITION_MISMATCH = "REJECT_POSITION_MISMATCH"
    REJECT_UNKNOWN_OPENING_TYPE = "REJECT_UNKNOWN_OPENING_TYPE"


class FollowDecisionResult(BaseModel):
    allowed: bool
    decision: FollowDecisionKind
    reasons: list[str] = Field(default_factory=list)
    paper_size_usdc: float = 0.0


def decide_follow_signal(
    *,
    signal_age_ms: int,
    wallet_action: str,
    spread_bps: float,
    slippage_bps: float,
    wallet_score: float,
    pattern_score: float,
    max_signal_age_ms: int = 3000,
    max_spread_bps: float = 20.0,
    max_slippage_bps: float = 25.0,
) -> FollowDecisionResult:
    if wallet_action.upper() == "REDUCE":
        return FollowDecisionResult(allowed=False, decision=FollowDecisionKind.REJECT_WALLET_REDUCING, reasons=["wallet_reducing"])
    if wallet_action.upper() == "CLOSE":
        return FollowDecisionResult(allowed=False, decision=FollowDecisionKind.REJECT_WALLET_CLOSING, reasons=["wallet_closing"])
    if signal_age_ms > max_signal_age_ms:
        return FollowDecisionResult(allowed=False, decision=FollowDecisionKind.REJECT_TOO_LATE, reasons=["signal_stale"])
    if spread_bps > max_spread_bps:
        return FollowDecisionResult(allowed=False, decision=FollowDecisionKind.REJECT_SPREAD_TOO_WIDE, reasons=["spread_too_wide"])
    if slippage_bps > max_slippage_bps:
        return FollowDecisionResult(allowed=False, decision=FollowDecisionKind.REJECT_SLIPPAGE_TOO_HIGH, reasons=["slippage_too_high"])
    if wallet_score < 70:
        return FollowDecisionResult(allowed=False, decision=FollowDecisionKind.REJECT_WALLET_SCORE_LOW, reasons=["wallet_score_low"])
    if pattern_score < 65:
        return FollowDecisionResult(allowed=False, decision=FollowDecisionKind.REJECT_PATTERN_SCORE_LOW, reasons=["pattern_score_low"])
    return FollowDecisionResult(
        allowed=True,
        decision=FollowDecisionKind.PAPER_FOLLOW_ALLOWED,
        reasons=["paper_only_risk_passed"],
        paper_size_usdc=1.0,
    )
