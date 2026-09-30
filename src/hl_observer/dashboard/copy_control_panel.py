"""Read-only panel describing the local copy session."""

from __future__ import annotations

from hl_observer.copy_wallet.copy_session_controller import CopySessionState


def build_copy_control_panel(state: CopySessionState) -> dict[str, object]:
    return {
        "title": "Copy session",
        "session_id": state.session_id,
        "status": state.status,
        "watchlist_count": len(state.watchlist),
        "copy_ratio": state.copy_ratio,
        "paper_only": state.paper_only,
        "real_execution": state.real_execution,
    }


__all__ = ["build_copy_control_panel"]
