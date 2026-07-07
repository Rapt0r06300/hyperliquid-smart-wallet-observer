"""Resolve multi-leader copy conflicts before a paper entry is allowed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from hl_observer.copy_mode.wallet_mirror_runtime import MirrorCandidate


@dataclass(frozen=True, slots=True)
class CopyConflictDecision:
    accepted: bool
    coin: str
    side: str
    confidence_boost: float
    candidate_ids: tuple[str, ...] = field(default_factory=tuple)
    leader_wallets: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def resolve_copy_conflicts(
    candidates: Iterable[MirrorCandidate],
    *,
    min_same_side_leaders: int = 1,
    max_boost: float = 0.20,
) -> CopyConflictDecision:
    """Approve same-direction clusters and block opposite leader conflicts.

    The resolver is intentionally simple and deterministic: a same coin with
    mixed LONG/SHORT leaders becomes NO_TRADE; same-side leaders increase
    confidence but do not bypass later risk or slippage gates.
    """

    clean = [c for c in candidates if c.is_entry and not c.reason_codes and c.side in {"LONG", "SHORT"}]
    if not clean:
        return CopyConflictDecision(
            accepted=False,
            coin="",
            side="",
            confidence_boost=0.0,
            reason_codes=("NO_VALID_MIRROR_CANDIDATE",),
        )
    coins = {c.coin for c in clean}
    if len(coins) != 1:
        return CopyConflictDecision(
            accepted=False,
            coin=",".join(sorted(coins)),
            side="",
            confidence_boost=0.0,
            reason_codes=("MULTI_COIN_BATCH_NOT_SINGLE_DECISION",),
        )
    sides = {c.side for c in clean}
    if len(sides) != 1:
        return CopyConflictDecision(
            accepted=False,
            coin=clean[0].coin,
            side="CONFLICT",
            confidence_boost=0.0,
            candidate_ids=tuple(c.candidate_id for c in clean),
            leader_wallets=tuple(dict.fromkeys(c.leader_wallet for c in clean)),
            reason_codes=("CONFLICTING_LEADERS",),
        )

    leaders = tuple(dict.fromkeys(c.leader_wallet for c in clean))
    if len(leaders) < int(min_same_side_leaders):
        return CopyConflictDecision(
            accepted=False,
            coin=clean[0].coin,
            side=clean[0].side,
            confidence_boost=0.0,
            candidate_ids=tuple(c.candidate_id for c in clean),
            leader_wallets=leaders,
            reason_codes=("LEADER_CONFIRMATION_TOO_LOW",),
        )

    boost = min(float(max_boost), max(0.0, (len(leaders) - 1) * 0.05))
    return CopyConflictDecision(
        accepted=True,
        coin=clean[0].coin,
        side=clean[0].side,
        confidence_boost=round(boost, 8),
        candidate_ids=tuple(c.candidate_id for c in clean),
        leader_wallets=leaders,
        reason_codes=("SAME_DIRECTION_LEADERS",) if len(leaders) > 1 else (),
    )


__all__ = ["CopyConflictDecision", "resolve_copy_conflicts"]
