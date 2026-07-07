"""Resolve opposing leader actions before paper entries are built."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


LONG_WORDS = ("LONG", "BUY", "OPEN_LONG")
SHORT_WORDS = ("SHORT", "SELL", "OPEN_SHORT")


@dataclass(frozen=True, slots=True)
class LeaderVote:
    wallet: str
    coin: str
    side: str
    score: float = 1.0
    observed_at_ms: int = 0


@dataclass(frozen=True, slots=True)
class CopyConflictDecision:
    coin: str
    decision: str
    winning_side: str | None
    long_score: float
    short_score: float
    reasons: tuple[str, ...]


def _side_bucket(side: str) -> str:
    side_u = str(side).upper()
    if any(word in side_u for word in LONG_WORDS):
        return "LONG"
    if any(word in side_u for word in SHORT_WORDS):
        return "SHORT"
    return "UNKNOWN"


def resolve_copy_conflict(votes: Iterable[LeaderVote | dict[str, object]], *, min_majority_ratio: float = 1.35) -> CopyConflictDecision:
    rows: list[LeaderVote] = []
    for vote in votes:
        if isinstance(vote, LeaderVote):
            rows.append(vote)
        else:
            rows.append(
                LeaderVote(
                    wallet=str(vote.get("wallet") or ""),
                    coin=str(vote.get("coin") or "").upper(),
                    side=str(vote.get("side") or vote.get("action") or ""),
                    score=float(vote.get("score") or 1.0),
                    observed_at_ms=int(vote.get("observed_at_ms") or 0),
                )
            )
    coin = rows[0].coin if rows else ""
    long_score = sum(max(v.score, 0.0) for v in rows if _side_bucket(v.side) == "LONG")
    short_score = sum(max(v.score, 0.0) for v in rows if _side_bucket(v.side) == "SHORT")
    if long_score <= 0 and short_score <= 0:
        return CopyConflictDecision(coin=coin, decision="NO_TRADE", winning_side=None, long_score=0.0, short_score=0.0, reasons=("NO_DIRECTIONAL_VOTES",))
    if long_score > 0 and short_score > 0:
        ratio = max(long_score, short_score) / max(min(long_score, short_score), 1e-9)
        if ratio < float(min_majority_ratio):
            return CopyConflictDecision(
                coin=coin,
                decision="NO_TRADE",
                winning_side=None,
                long_score=round(long_score, 8),
                short_score=round(short_score, 8),
                reasons=("CONFLICTING_LEADERS",),
            )
    winning_side = "LONG" if long_score >= short_score else "SHORT"
    return CopyConflictDecision(
        coin=coin,
        decision="FOLLOW",
        winning_side=winning_side,
        long_score=round(long_score, 8),
        short_score=round(short_score, 8),
        reasons=(),
    )


__all__ = ["CopyConflictDecision", "LeaderVote", "resolve_copy_conflict"]
