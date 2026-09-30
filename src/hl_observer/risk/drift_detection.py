"""Detect tracking drift between leader and local paper position."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DriftDetection:
    drift_bps: float
    triggered: bool
    reason: str | None


def detect_tracking_drift_bps(
    *,
    leader_entry_price: float,
    paper_entry_price: float,
    threshold_bps: float = 25.0,
) -> DriftDetection:
    leader = float(leader_entry_price or 0.0)
    paper = float(paper_entry_price or 0.0)
    if leader <= 0 or paper <= 0:
        return DriftDetection(0.0, True, "DRIFT_INPUT_INVALID")
    drift = abs(paper / leader - 1.0) * 10_000.0
    if drift >= float(threshold_bps):
        return DriftDetection(round(drift, 8), True, "TRACKING_DRIFT_TOO_HIGH")
    return DriftDetection(round(drift, 8), False, None)


__all__ = ["DriftDetection", "detect_tracking_drift_bps"]
