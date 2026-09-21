"""Strict qualification of collection windows for replay/backtest use."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

SAFE = "SAFE"
PARTIAL = "PARTIAL"
REJECT = "REJECT"
NO_DATA = "NO_DATA"


@dataclass(frozen=True, slots=True)
class WindowQualityReport:
    status: str
    event_count: int
    start_ts_ms: int | None
    end_ts_ms: int | None
    gap_count: int
    duplicate_count: int
    regression_count: int
    missing_timestamp_count: int
    desync_count: int
    stale_count: int
    max_receive_gap_ms: int | None
    reconciliation_status: str
    reasons: tuple[str, ...]

    @property
    def validation_allowed(self) -> bool:
        return self.status == SAFE

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "validation_allowed": self.validation_allowed}


def qualify_window(
    events: Iterable[Mapping[str, Any]],
    *,
    reconciliation_status: str = "MATCHED",
    max_receive_gap_ms: int | None = None,
    allowed_receive_gap_ms: int | None = None,
    min_events: int = 1,
) -> WindowQualityReport:
    rows = list(events)
    if not rows:
        return WindowQualityReport(
            status=NO_DATA,
            event_count=0,
            start_ts_ms=None,
            end_ts_ms=None,
            gap_count=0,
            duplicate_count=0,
            regression_count=0,
            missing_timestamp_count=0,
            desync_count=0,
            stale_count=0,
            max_receive_gap_ms=None,
            reconciliation_status=str(reconciliation_status).upper(),
            reasons=("NO_DATA",),
        )

    receive_times: list[int] = []
    gaps = duplicates = regressions = missing = desync = stale = 0
    for row in rows:
        recv = _int_or_none(
            row.get("receive_ts_ms", row.get("received_ts_ms", row.get("recv_wall_ts_ms")))
        )
        exchange = _int_or_none(row.get("exchange_ts_ms"))
        if recv is None or exchange is None:
            missing += 1
        if recv is not None:
            receive_times.append(recv)
        gaps += _count(row, "gap_count", "gaps")
        duplicates += _count(row, "duplicate_count", "duplicates")
        regressions += _count(row, "regression_count", "regressions")
        quality = str(row.get("quality") or "").upper()
        if quality == "DESYNC":
            desync += 1
        if quality == "STALE":
            stale += 1

    receive_times.sort()
    observed_max_gap = (
        max((right - left for left, right in zip(receive_times, receive_times[1:])), default=0)
        if len(receive_times) >= 2
        else None
    )
    effective_gap = max_receive_gap_ms if max_receive_gap_ms is not None else observed_max_gap

    reasons: list[str] = []
    if len(rows) < max(1, int(min_events)):
        reasons.append("INSUFFICIENT_EVENTS")
    if gaps:
        reasons.append("SEQUENCE_GAPS")
    if regressions:
        reasons.append("SEQUENCE_OR_TIME_REGRESSION")
    if missing:
        reasons.append("MISSING_TIMESTAMPS")
    if desync:
        reasons.append("DESYNC_EVENTS")
    if stale:
        reasons.append("STALE_EVENTS")
    if (
        allowed_receive_gap_ms is not None
        and effective_gap is not None
        and effective_gap > int(allowed_receive_gap_ms)
    ):
        reasons.append("RECEIVE_GAP_TOO_LARGE")

    reconciliation = str(reconciliation_status or "UNVERIFIED").upper()
    if reconciliation != "MATCHED":
        reasons.append(f"RECONCILIATION_{reconciliation}")

    severe = gaps or regressions or desync
    if severe:
        status = REJECT
    elif reasons:
        status = PARTIAL
    else:
        status = SAFE

    return WindowQualityReport(
        status=status,
        event_count=len(rows),
        start_ts_ms=min(receive_times) if receive_times else None,
        end_ts_ms=max(receive_times) if receive_times else None,
        gap_count=gaps,
        duplicate_count=duplicates,
        regression_count=regressions,
        missing_timestamp_count=missing,
        desync_count=desync,
        stale_count=stale,
        max_receive_gap_ms=effective_gap,
        reconciliation_status=reconciliation,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _count(row: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = _int_or_none(row.get(key))
        if value is not None:
            return max(0, value)
    return 0


__all__ = [
    "NO_DATA",
    "PARTIAL",
    "REJECT",
    "SAFE",
    "WindowQualityReport",
    "qualify_window",
]
