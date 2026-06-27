"""Per-stream Quality Mode: OK / DEGRADED / BAD (S4 — V9 fusion, mlmodelpoly A5).

Each data stream (book, trades, mids, candles, user events) is graded on
freshness and completeness. The aggregate across streams is the worst grade
(deny-by-default). A BAD stream forces NO_TRADE upstream.

SAFETY: grading never invents data; it only describes what is present.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - py<3.11 fallback
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class QualityLevel(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    BAD = "BAD"


_RANK = {QualityLevel.OK: 0, QualityLevel.DEGRADED: 1, QualityLevel.BAD: 2}


@dataclass(frozen=True, slots=True)
class StreamQuality:
    stream: str
    level: QualityLevel
    reasons: tuple[str, ...]
    age_ms: int | None


def assess_stream(
    stream: str,
    *,
    age_ms: int | None,
    degraded_after_ms: int,
    bad_after_ms: int,
    missing_fields: tuple[str, ...] = (),
    present: bool = True,
) -> StreamQuality:
    """Grade a single stream from freshness + completeness."""
    reasons: list[str] = []
    level = QualityLevel.OK

    if not present:
        return StreamQuality(stream, QualityLevel.BAD, ("STREAM_ABSENT",), age_ms)

    if age_ms is None:
        reasons.append("NO_TIMESTAMP")
        level = QualityLevel.DEGRADED
    else:
        if age_ms >= bad_after_ms:
            reasons.append("STREAM_STALE_BAD")
            level = QualityLevel.BAD
        elif age_ms >= degraded_after_ms:
            reasons.append("STREAM_STALE_DEGRADED")
            level = _max_level(level, QualityLevel.DEGRADED)

    if missing_fields:
        reasons.append("MISSING_FIELDS:" + ",".join(sorted(missing_fields)))
        # missing fields degrade; many missing fields is BAD
        level = _max_level(level, QualityLevel.BAD if len(missing_fields) >= 3 else QualityLevel.DEGRADED)

    if not reasons:
        reasons.append("STREAM_OK")
    return StreamQuality(stream, level, tuple(reasons), age_ms)


def aggregate_quality(streams: list[StreamQuality]) -> QualityLevel:
    """Worst-of aggregation across streams (deny-by-default)."""
    if not streams:
        return QualityLevel.BAD
    worst = QualityLevel.OK
    for sq in streams:
        worst = _max_level(worst, sq.level)
    return worst


def is_tradeable(level: QualityLevel) -> bool:
    """Only OK and DEGRADED are tradeable; BAD blocks (NO_TRADE)."""
    return level != QualityLevel.BAD


def _max_level(a: QualityLevel, b: QualityLevel) -> QualityLevel:
    return a if _RANK[a] >= _RANK[b] else b
