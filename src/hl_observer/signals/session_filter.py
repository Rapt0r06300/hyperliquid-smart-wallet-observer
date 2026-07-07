"""V15 #205 — Session / hour filter (avoid dead, illiquid hours)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_DEAD_SESSION"

# UTC hours that tend to be thin (configurable). Default: late-US / pre-Asia lull.
DEFAULT_DEAD_HOURS_UTC: tuple[int, ...] = (3, 4, 5)


@dataclass(frozen=True, slots=True)
class SessionStatus:
    hour_utc: int
    active: bool
    reason: str | None


def session_status(hour_utc: int, *, dead_hours_utc: Sequence[int] = DEFAULT_DEAD_HOURS_UTC) -> SessionStatus:
    h = int(hour_utc) % 24
    if h in set(int(x) for x in dead_hours_utc):
        return SessionStatus(h, False, "DEAD_HOUR")
    return SessionStatus(h, True, None)


def apply_session_promotion(
    *, score_reason: str, session_active: bool | None, authoritative: bool, accept_marker: str = ACCEPT_MARKER,
) -> str:
    if authoritative and score_reason == accept_marker and session_active is False:
        return REJECT_REASON
    return score_reason


__all__ = ["ACCEPT_MARKER", "REJECT_REASON", "DEFAULT_DEAD_HOURS_UTC", "SessionStatus", "session_status", "apply_session_promotion"]
