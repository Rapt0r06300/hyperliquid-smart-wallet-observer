"""V14 #171 — Combined-subscription WS audit: backoff, anti-backpressure, gap recovery.

Pure policy + audit helpers (inspired by mlmodelpoly's collector/ws_client). They DECIDE
nothing live; they validate that a combined `/stream?streams=a/b/c` consumer reconnects
with bounded backoff, drops/​warns under backpressure instead of stalling, and detects
sequence gaps so the indexer can backfill. read-only / paper-only: no socket here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


DEFAULT_BACKOFF_SCHEDULE_S: tuple[int, ...] = (1, 2, 5, 10, 30)


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    schedule_s: tuple[int, ...] = DEFAULT_BACKOFF_SCHEDULE_S
    ping_interval_s: int = 20
    ping_timeout_s: int = 10

    def next_delay_s(self, attempt: int) -> int:
        """Bounded backoff: caps at the last step (never unbounded)."""
        if attempt <= 0:
            return int(self.schedule_s[0])
        idx = min(attempt, len(self.schedule_s) - 1)
        return int(self.schedule_s[idx])


def backpressure_decision(*, queue_len: int, max_len: int, soft_ratio: float = 0.8) -> str:
    """DROP_OLDEST when full, WARN past the soft watermark, else OK. Never block the reader."""
    if max_len <= 0:
        return "OK"
    if queue_len >= max_len:
        return "DROP_OLDEST"
    if queue_len >= int(max_len * soft_ratio):
        return "WARN"
    return "OK"


@dataclass(frozen=True, slots=True)
class SequenceGap:
    prev_seq: int
    next_seq: int
    missing: int


def detect_sequence_gaps(seqs: Sequence[int]) -> tuple[tuple[SequenceGap, ...], int]:
    """Find gaps in a monotonically increasing sequence id stream (per channel)."""
    gaps: list[SequenceGap] = []
    total_missing = 0
    prev: int | None = None
    for s in seqs:
        si = int(s)
        if prev is not None and si > prev + 1:
            missing = si - prev - 1
            gaps.append(SequenceGap(prev, si, missing))
            total_missing += missing
        if prev is None or si > prev:
            prev = si
    return tuple(gaps), total_missing


@dataclass(frozen=True, slots=True)
class WsHealthAudit:
    reconnects: int
    backpressure_warns: int
    backpressure_drops: int
    sequence_gaps: int
    missing_messages: int
    last_msg_age_ms: int | None
    status: str


def audit_ws_health(
    *,
    reconnects: int,
    backpressure_warns: int,
    backpressure_drops: int,
    seqs_by_channel: dict[str, Sequence[int]] | None = None,
    last_msg_age_ms: int | None = None,
    stale_after_ms: int = 30_000,
) -> WsHealthAudit:
    gaps = 0
    missing = 0
    for _ch, seqs in (seqs_by_channel or {}).items():
        g, m = detect_sequence_gaps(seqs)
        gaps += len(g)
        missing += m
    if last_msg_age_ms is not None and last_msg_age_ms > stale_after_ms:
        status = "STALE_NO_RECENT_MESSAGES"
    elif backpressure_drops > 0 or missing > 0:
        status = "DEGRADED_GAPS_OR_DROPS"
    elif backpressure_warns > 0 or reconnects > 0:
        status = "RECOVERED"
    else:
        status = "OK"
    return WsHealthAudit(
        reconnects=int(reconnects),
        backpressure_warns=int(backpressure_warns),
        backpressure_drops=int(backpressure_drops),
        sequence_gaps=gaps,
        missing_messages=missing,
        last_msg_age_ms=last_msg_age_ms,
        status=status,
    )


__all__ = [
    "DEFAULT_BACKOFF_SCHEDULE_S",
    "BackoffPolicy",
    "backpressure_decision",
    "SequenceGap",
    "detect_sequence_gaps",
    "WsHealthAudit",
    "audit_ws_health",
]
