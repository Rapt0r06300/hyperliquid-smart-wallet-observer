"""Local copy-session controller, no external execution."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class CopySessionState:
    session_id: str
    status: str
    watchlist: tuple[str, ...]
    copy_ratio: float
    paper_only: bool = True
    real_execution: bool = False


def start_copy_session(session_id: str, *, watchlist: tuple[str, ...] = (), copy_ratio: float = 0.05) -> CopySessionState:
    return CopySessionState(session_id=str(session_id), status="RUNNING", watchlist=tuple(watchlist), copy_ratio=float(copy_ratio))


def stop_copy_session(state: CopySessionState) -> CopySessionState:
    return replace(state, status="STOPPED")


def update_copy_session(state: CopySessionState, *, watchlist: tuple[str, ...] | None = None, copy_ratio: float | None = None) -> CopySessionState:
    return replace(
        state,
        watchlist=tuple(watchlist) if watchlist is not None else state.watchlist,
        copy_ratio=float(copy_ratio) if copy_ratio is not None else state.copy_ratio,
    )


__all__ = ["CopySessionState", "start_copy_session", "stop_copy_session", "update_copy_session"]
