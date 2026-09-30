"""Strict replay-window qualification.

A window is SAFE only when the evidence requested by the caller is present. Missing
proof stays missing: no zero filling, no optimistic default reconciliation.
"""
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
    missing_monotonic_count: int
    desync_count: int
    stale_count: int
    connection_change_count: int
    max_receive_gap_ms: int | None
    max_transport_rtt_ms: float | None
    max_abs_clock_offset_ms: float | None
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
    reconciliation_status: str = "UNVERIFIED",
    max_receive_gap_ms: int | None = None,
    allowed_receive_gap_ms: int | None = None,
    allowed_transport_rtt_ms: float | None = None,
    allowed_abs_clock_offset_ms: float | None = None,
    min_events: int = 1,
    require_monotonic_clock: bool = True,
    duplicates_deduped: bool = False,
    required_channels: Iterable[str] = (),
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
            missing_monotonic_count=0,
            desync_count=0,
            stale_count=0,
            connection_change_count=0,
            max_receive_gap_ms=None,
            max_transport_rtt_ms=None,
            max_abs_clock_offset_ms=None,
            reconciliation_status=str(reconciliation_status or "UNVERIFIED").upper(),
            reasons=("NO_DATA",),
        )

    receive_times: list[int] = []
    transport_rtts: list[float] = []
    clock_offsets: list[float] = []
    connection_ids: list[str] = []
    observed_channels: set[str] = set()
    gaps = duplicates = regressions = missing = missing_mono = desync = stale = 0

    for row in rows:
        recv = _int_or_none(
            row.get("receive_ts_ms", row.get("received_ts_ms", row.get("recv_wall_ts_ms")))
        )
        exchange = _int_or_none(row.get("exchange_ts_ms"))
        mono = _int_or_none(
            row.get(
                "receive_mono_ns",
                row.get("local_monotonic_ns", row.get("recv_mono_ns")),
            )
        )
        if recv is None or exchange is None:
            missing += 1
        if require_monotonic_clock and mono is None:
            missing_mono += 1
        if recv is not None:
            receive_times.append(recv)

        channel = str(row.get("channel") or "").strip()
        if channel:
            observed_channels.add(channel)

        connection = str(row.get("connection_id") or "").strip()
        if connection:
            connection_ids.append(connection)

        gaps += _count(row, "gap_count", "gaps")
        duplicates += _count(row, "duplicate_count", "duplicates")
        regressions += _count(row, "regression_count", "regressions")
        quality = str(row.get("quality") or "").upper()
        if quality == "DESYNC":
            desync += 1
        if quality == "STALE":
            stale += 1

        summary = row.get("parsed_summary")
        summary_map = summary if isinstance(summary, Mapping) else {}
        rtt = _float_or_none(
            row.get("transport_rtt_ms", summary_map.get("transport_rtt_ms"))
        )
        offset = _float_or_none(
            row.get("clock_offset_ms", summary_map.get("clock_offset_ms"))
        )
        if rtt is not None:
            transport_rtts.append(rtt)
        if offset is not None:
            clock_offsets.append(abs(offset))

    receive_times.sort()
    observed_max_gap = (
        max((right - left for left, right in zip(receive_times, receive_times[1:])), default=0)
        if len(receive_times) >= 2
        else None
    )
    effective_gap = max_receive_gap_ms if max_receive_gap_ms is not None else observed_max_gap
    max_rtt = max(transport_rtts) if transport_rtts else None
    max_offset = max(clock_offsets) if clock_offsets else None
    connection_changes = sum(
        1 for left, right in zip(connection_ids, connection_ids[1:]) if left != right
    )

    reasons: list[str] = []
    if len(rows) < max(1, int(min_events)):
        reasons.append("INSUFFICIENT_EVENTS")
    if gaps:
        reasons.append("SEQUENCE_GAPS")
    if duplicates and not duplicates_deduped:
        reasons.append("DUPLICATES_PRESENT")
    if regressions:
        reasons.append("SEQUENCE_OR_TIME_REGRESSION")
    if missing:
        reasons.append("MISSING_TIMESTAMPS")
    if missing_mono:
        reasons.append("MISSING_MONOTONIC_TIMESTAMP")
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
    if allowed_transport_rtt_ms is not None:
        if max_rtt is None:
            reasons.append("MISSING_TRANSPORT_RTT")
        elif max_rtt > float(allowed_transport_rtt_ms):
            reasons.append("TRANSPORT_RTT_TOO_HIGH")
    if allowed_abs_clock_offset_ms is not None:
        if max_offset is None:
            reasons.append("MISSING_CLOCK_OFFSET")
        elif max_offset > float(allowed_abs_clock_offset_ms):
            reasons.append("CLOCK_OFFSET_TOO_LARGE")

    required = {str(value).strip() for value in required_channels if str(value).strip()}
    missing_channels = sorted(required - observed_channels)
    if missing_channels:
        reasons.append("MISSING_REQUIRED_CHANNELS:" + ",".join(missing_channels))

    reconciliation = str(reconciliation_status or "UNVERIFIED").upper()
    if reconciliation != "MATCHED":
        reasons.append(f"RECONCILIATION_{reconciliation}")
    elif connection_changes:
        # A reconnect is acceptable only after a matched post-hoc reconciliation.
        # It remains observable in the report even though it does not block SAFE.
        pass

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
        missing_monotonic_count=missing_mono,
        desync_count=desync,
        stale_count=stale,
        connection_change_count=connection_changes,
        max_receive_gap_ms=effective_gap,
        max_transport_rtt_ms=max_rtt,
        max_abs_clock_offset_ms=max_offset,
        reconciliation_status=reconciliation,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
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
