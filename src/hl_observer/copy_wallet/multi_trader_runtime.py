"""Small multi-leader copy runtime facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .copy_conflict_resolver import CopyConflictDecision, LeaderVote, resolve_copy_conflict


@dataclass(frozen=True, slots=True)
class MultiTraderDecision:
    coin: str
    decision: str
    side: str | None
    leaders_seen: int
    conflict: CopyConflictDecision


def evaluate_multi_trader_votes(votes: Iterable[LeaderVote | dict[str, object]], *, min_majority_ratio: float = 1.35) -> MultiTraderDecision:
    vote_rows = tuple(votes)
    conflict = resolve_copy_conflict(vote_rows, min_majority_ratio=min_majority_ratio)
    return MultiTraderDecision(
        coin=conflict.coin,
        decision=conflict.decision,
        side=conflict.winning_side,
        leaders_seen=len(vote_rows),
        conflict=conflict,
    )


__all__ = ["MultiTraderDecision", "evaluate_multi_trader_votes"]
