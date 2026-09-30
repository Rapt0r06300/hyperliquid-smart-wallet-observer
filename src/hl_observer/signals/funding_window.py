"""V15 #197 — Funding-window avoidance: don't enter just before a funding flip."""

from __future__ import annotations

from dataclasses import dataclass

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_FUNDING_WINDOW_IMMINENT"


@dataclass(frozen=True, slots=True)
class FundingWindowStatus:
    seconds_to_funding: float
    in_avoid_window: bool
    status: str            # CLEAR | AVOID


def funding_window_status(*, seconds_to_funding: float, avoid_window_s: float = 120.0) -> FundingWindowStatus:
    avoid = 0.0 <= float(seconds_to_funding) <= float(avoid_window_s)
    return FundingWindowStatus(float(seconds_to_funding), avoid, "AVOID" if avoid else "CLEAR")


def apply_funding_window_promotion(
    *, score_reason: str, in_avoid_window: bool | None, authoritative: bool, accept_marker: str = ACCEPT_MARKER,
) -> str:
    if authoritative and score_reason == accept_marker and in_avoid_window is True:
        return REJECT_REASON
    return score_reason


__all__ = ["ACCEPT_MARKER", "REJECT_REASON", "FundingWindowStatus", "funding_window_status", "apply_funding_window_promotion"]
