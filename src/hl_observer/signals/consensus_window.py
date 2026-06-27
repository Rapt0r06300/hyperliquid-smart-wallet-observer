"""V14 #175 — Hot consensus window (≈4 s): only enter while the signal is fresh.

The losing 24/06 run chased moves that had already left; the snapshot said the hot
consensus targets ≈4 s. This gate only lets an entry through inside a fresh window and
vetoes outside it. Pure; promotion is opt-in and can only reduce trades.
"""

from __future__ import annotations

from dataclasses import dataclass

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_OUTSIDE_CONSENSUS_WINDOW"


@dataclass(frozen=True, slots=True)
class ConsensusWindowConfig:
    hot_window_ms: int = 4_000
    max_window_ms: int = 15_000


@dataclass(frozen=True, slots=True)
class ConsensusWindowStatus:
    age_ms: int
    in_hot_window: bool
    in_window: bool
    status: str   # HOT | FRESH | STALE


def consensus_window_status(
    *,
    first_seen_ms: int,
    now_ms: int,
    config: ConsensusWindowConfig | None = None,
) -> ConsensusWindowStatus:
    cfg = config or ConsensusWindowConfig()
    age = max(0, int(now_ms) - int(first_seen_ms))
    in_hot = age <= cfg.hot_window_ms
    in_win = age <= cfg.max_window_ms
    status = "HOT" if in_hot else ("FRESH" if in_win else "STALE")
    return ConsensusWindowStatus(age_ms=age, in_hot_window=in_hot, in_window=in_win, status=status)


def apply_consensus_window_promotion(
    *,
    score_reason: str,
    in_window: bool | None,
    authoritative: bool,
    accept_marker: str = ACCEPT_MARKER,
) -> str:
    """Veto entries outside the fresh window. None (unknown) never blocks. Shadow = no-op."""
    if authoritative and score_reason == accept_marker and in_window is False:
        return REJECT_REASON
    return score_reason


__all__ = [
    "ACCEPT_MARKER",
    "REJECT_REASON",
    "ConsensusWindowConfig",
    "ConsensusWindowStatus",
    "consensus_window_status",
    "apply_consensus_window_promotion",
]
