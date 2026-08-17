"""Certified wall-clock boundary for Lead-Lag economic proofs.

Historical rows that only carry ``recu_ns`` remain in the archive, but a
process-local monotonic clock cannot establish ordering across restarts or
shards.  Economic proof therefore rejects those rows instead of silently
mixing incompatible monotonic epochs.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any, Iterator

from hl_observer.backtesting import lead_lag_shadow

CERTIFIED_TIMESTAMP_POLICY = "ts_wall_ms_or_recv_wall_ts_ms_required"


def certified_event_time_ns(row: Mapping[str, Any]) -> int | None:
    wall_ms = row.get("ts_wall_ms", row.get("recv_wall_ts_ms"))
    if wall_ms is None:
        return None
    try:
        value = int(float(wall_ms) * 1_000_000.0)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None


@contextmanager
def _certified_clock_patch() -> Iterator[None]:
    original = lead_lag_shadow._event_time_ns
    lead_lag_shadow._event_time_ns = certified_event_time_ns
    try:
        yield
    finally:
        lead_lag_shadow._event_time_ns = original


def backtest_with_certified_wall_clock(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run canonical Lead-Lag while excluding monotonic-only timestamps."""

    with _certified_clock_patch():
        result = lead_lag_shadow.backtest(*args, **kwargs)
    if isinstance(result, dict):
        result["timestamp_certification"] = {
            "policy": CERTIFIED_TIMESTAMP_POLICY,
            "wall_clock_required": True,
            "monotonic_only_rows_eligible_for_economic_proof": False,
            "archive_rows_preserved": True,
        }
    return result


def certified_protocol_signature() -> dict[str, Any]:
    signature = dict(lead_lag_shadow.walk_forward_protocol_signature())
    signature["timestamp_clock"] = CERTIFIED_TIMESTAMP_POLICY
    signature["monotonic_only_rows_eligible_for_economic_proof"] = False
    return signature


__all__ = [
    "CERTIFIED_TIMESTAMP_POLICY",
    "backtest_with_certified_wall_clock",
    "certified_event_time_ns",
    "certified_protocol_signature",
]
