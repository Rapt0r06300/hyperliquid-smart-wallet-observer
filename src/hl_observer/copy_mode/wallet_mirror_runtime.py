"""Wallet mirror runtime primitives for Hyperliquid paper simulation.

This ports the useful copy-trader pattern into HyperSmart without importing a
foreign execution surface: leader deltas become paper-only mirror candidates,
then a risk/sizing layer may convert them to ``PaperIntent`` objects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Iterable

from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.strategies.models import IntentAction, IntentSide, PaperIntent, StrategyKind


@dataclass(frozen=True, slots=True)
class MirrorCandidate:
    candidate_id: str
    leader_wallet: str
    coin: str
    leader_action: str
    side: str
    leader_size: float
    leader_price: float
    leader_time: int | None
    observed_time: int
    copy_ratio: float
    wallet_score: float
    copyability_score: float
    slippage_budget_bps: float
    source_fill_refs: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_entry(self) -> bool:
        return self.leader_action in {
            LifecycleAction.OPEN_LONG.value,
            LifecycleAction.OPEN_SHORT.value,
            LifecycleAction.ADD.value,
            LifecycleAction.INCREASE.value,
        }

    @property
    def paper_only(self) -> bool:
        return True

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["paper_only"] = True
        payload["external_action"] = False
        return payload


@dataclass(frozen=True, slots=True)
class MirrorRuntimeConfig:
    copy_ratio: float = 0.05
    min_wallet_score: float = 0.55
    min_copyability_score: float = 0.55
    max_signal_age_ms: int = 3_000
    slippage_budget_bps: float = 18.0
    strategy_id: str = "wallet_mirror_copy_follow"


def mirror_candidate_from_delta(
    delta: LeaderDelta,
    *,
    leader_price: float,
    observed_time_ms: int,
    wallet_score: float,
    copyability_score: float,
    config: MirrorRuntimeConfig | None = None,
    source_fill_refs: Iterable[str] = (),
) -> MirrorCandidate:
    """Build a paper mirror candidate from a leader delta.

    Ambiguous, stale, low-score or non-entry deltas are still represented, but
    they carry reason codes and will not become an accepted paper intent.
    """

    cfg = config or MirrorRuntimeConfig()
    reasons = list(delta.reason_codes)
    side = _side_from_delta(delta)
    if side is None:
        side = "UNKNOWN"
        reasons.append("MIRROR_SIDE_UNKNOWN")
    if not delta.is_entry:
        reasons.append("MIRROR_ENTRY_ONLY")
    if delta.confidence <= 0:
        reasons.append("LEADER_DELTA_LOW_CONFIDENCE")
    if delta.leader_event_time_ms is None:
        reasons.append("LEADER_TIME_MISSING")
    else:
        age_ms = max(0, int(observed_time_ms) - int(delta.leader_event_time_ms))
        if age_ms > cfg.max_signal_age_ms:
            reasons.append("MIRROR_SIGNAL_TOO_OLD")
    if float(leader_price or 0.0) <= 0:
        reasons.append("LEADER_PRICE_INVALID")
    if wallet_score < cfg.min_wallet_score:
        reasons.append("WALLET_SCORE_TOO_LOW")
    if copyability_score < cfg.min_copyability_score:
        reasons.append("COPYABILITY_TOO_LOW")

    fill_refs = tuple(str(ref) for ref in source_fill_refs if str(ref))
    if delta.evidence_ref and delta.evidence_ref not in fill_refs:
        fill_refs = (*fill_refs, delta.evidence_ref)

    return MirrorCandidate(
        candidate_id=_candidate_id(delta, leader_price, observed_time_ms, wallet_score, copyability_score, fill_refs),
        leader_wallet=delta.wallet.lower(),
        coin=delta.coin.upper(),
        leader_action=delta.action.value,
        side=side,
        leader_size=abs(float(delta.delta_size or delta.current_size or 0.0)),
        leader_price=float(leader_price or 0.0),
        leader_time=delta.leader_event_time_ms,
        observed_time=int(observed_time_ms),
        copy_ratio=float(cfg.copy_ratio),
        wallet_score=round(float(wallet_score), 8),
        copyability_score=round(float(copyability_score), 8),
        slippage_budget_bps=float(cfg.slippage_budget_bps),
        source_fill_refs=fill_refs,
        confidence=round(float(delta.confidence), 8),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def candidate_to_paper_intent(
    candidate: MirrorCandidate,
    *,
    target_notional_usdt: float,
    created_at_ms: int | None = None,
    strategy_id: str | None = None,
) -> PaperIntent:
    """Convert an accepted mirror candidate to a paper-only intent."""

    side = _intent_side(candidate.side)
    action = IntentAction.ADD if candidate.leader_action in {LifecycleAction.ADD.value, LifecycleAction.INCREASE.value} else IntentAction.OPEN
    reasons = (
        f"leader_wallet={candidate.leader_wallet}",
        f"leader_action={candidate.leader_action}",
        f"copy_ratio={candidate.copy_ratio:.8f}",
        f"wallet_score={candidate.wallet_score:.4f}",
        f"copyability_score={candidate.copyability_score:.4f}",
        f"candidate_id={candidate.candidate_id}",
        "strategy_kind=" + StrategyKind.COPY_FOLLOW.value,
    )
    return PaperIntent(
        strategy_id=strategy_id or "wallet_mirror_copy_follow",
        coin=candidate.coin,
        side=side,
        action=action,
        target_notional_usdt=max(0.0, float(target_notional_usdt or 0.0)),
        confidence=min(1.0, max(0.0, float(candidate.confidence))),
        reasons=reasons,
        created_at_ms=int(created_at_ms if created_at_ms is not None else candidate.observed_time),
    )


def _side_from_delta(delta: LeaderDelta) -> str | None:
    action = delta.action
    if action is LifecycleAction.OPEN_LONG:
        return "LONG"
    if action is LifecycleAction.OPEN_SHORT:
        return "SHORT"
    if action in {LifecycleAction.ADD, LifecycleAction.INCREASE}:
        if delta.current_size > 0:
            return "LONG"
        if delta.current_size < 0:
            return "SHORT"
    return None


def _intent_side(side: str) -> IntentSide:
    if str(side).upper() == "LONG":
        return IntentSide.LONG
    if str(side).upper() == "SHORT":
        return IntentSide.SHORT
    return IntentSide.FLAT


def _candidate_id(
    delta: LeaderDelta,
    leader_price: float,
    observed_time_ms: int,
    wallet_score: float,
    copyability_score: float,
    source_fill_refs: tuple[str, ...],
) -> str:
    blob = "|".join(
        str(part)
        for part in (
            delta.delta_id,
            delta.wallet.lower(),
            delta.coin.upper(),
            delta.action.value,
            delta.delta_size,
            leader_price,
            observed_time_ms,
            wallet_score,
            copyability_score,
            ",".join(source_fill_refs),
        )
    )
    return "mirror:" + sha256(blob.encode("utf-8")).hexdigest()[:32]


__all__ = [
    "MirrorCandidate",
    "MirrorRuntimeConfig",
    "candidate_to_paper_intent",
    "mirror_candidate_from_delta",
]
