"""V15 #206 — Sequence/timestamp gap detection + data-quality veto.

If the data stream has sequence gaps or large timestamp holes, the snapshot is unreliable and
we must NOT decide on it. Pure detector + veto gate. read-only / paper-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_DATA_GAP"


@dataclass(frozen=True, slots=True)
class DataQualityStatus:
    seq_gaps: int
    timestamp_gaps: int
    max_ts_gap_ms: int
    ok: bool
    reason: str | None


def detect_timestamp_gaps(timestamps_ms: Sequence[int], *, max_gap_ms: int = 5_000) -> tuple[int, int]:
    """Return (n_gaps, max_gap_ms) over an ascending timestamp stream."""
    ts = sorted(int(t) for t in timestamps_ms)
    gaps = 0
    biggest = 0
    for i in range(1, len(ts)):
        d = ts[i] - ts[i - 1]
        if d > max_gap_ms:
            gaps += 1
        biggest = max(biggest, d)
    return gaps, biggest


def data_quality_status(
    *,
    sequence_numbers: Sequence[int] | None = None,
    timestamps_ms: Sequence[int] | None = None,
    max_gap_ms: int = 5_000,
) -> DataQualityStatus:
    seq_gaps = 0
    if sequence_numbers:
        s = sorted(int(x) for x in sequence_numbers)
        for i in range(1, len(s)):
            if s[i] > s[i - 1] + 1:
                seq_gaps += 1
    ts_gaps, biggest = (0, 0)
    if timestamps_ms:
        ts_gaps, biggest = detect_timestamp_gaps(timestamps_ms, max_gap_ms=max_gap_ms)
    ok = (seq_gaps == 0 and ts_gaps == 0)
    reason = None if ok else ("SEQUENCE_GAP" if seq_gaps else "TIMESTAMP_GAP")
    return DataQualityStatus(seq_gaps, ts_gaps, biggest, ok, reason)


def apply_data_quality_promotion(
    *, score_reason: str, data_ok: bool | None, authoritative: bool, accept_marker: str = ACCEPT_MARKER,
) -> str:
    if authoritative and score_reason == accept_marker and data_ok is False:
        return REJECT_REASON
    return score_reason


__all__ = [
    "ACCEPT_MARKER", "REJECT_REASON", "DataQualityStatus",
    "detect_timestamp_gaps", "data_quality_status", "apply_data_quality_promotion",
]
