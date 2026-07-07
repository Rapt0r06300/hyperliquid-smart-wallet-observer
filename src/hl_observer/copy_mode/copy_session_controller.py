"""Local-only copy session start/stop state."""

from __future__ import annotations

from dataclasses import dataclass, replace

try:  # Python 3.11+
    from enum import StrEnum
except ImportError:  # Python 3.10 fallback
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class CopySessionState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


@dataclass(frozen=True, slots=True)
class CopySession:
    session_id: str
    state: CopySessionState = CopySessionState.STOPPED
    paper_only: bool = True
    external_action: bool = False
    started_at_ms: int | None = None
    stopped_at_ms: int | None = None
    reason: str | None = None


def start_copy_session(session: CopySession, *, now_ms: int) -> CopySession:
    return replace(session, state=CopySessionState.RUNNING, started_at_ms=int(now_ms), stopped_at_ms=None, reason="LOCAL_START")


def stop_copy_session(session: CopySession, *, now_ms: int, reason: str = "LOCAL_STOP") -> CopySession:
    return replace(session, state=CopySessionState.STOPPED, stopped_at_ms=int(now_ms), reason=reason)


def pause_copy_session(session: CopySession, *, reason: str = "LOCAL_PAUSE") -> CopySession:
    return replace(session, state=CopySessionState.PAUSED, reason=reason)


__all__ = ["CopySession", "CopySessionState", "pause_copy_session", "start_copy_session", "stop_copy_session"]
