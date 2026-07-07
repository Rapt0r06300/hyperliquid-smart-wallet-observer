"""Full-refresh fallback (V12, repo 05): when too many patches are missed, refresh fully.

If the client's last seen revision lags the server by more than max_gap (or is unknown), a
full authoritative snapshot is required instead of incremental patches. Pure.
"""

from __future__ import annotations


def needs_full_refresh(last_seen_revision: int | None, server_revision: int, *, max_gap: int = 100) -> bool:
    if last_seen_revision is None:
        return True
    gap = int(server_revision) - int(last_seen_revision)
    return gap < 0 or gap > int(max_gap)


__all__ = ["needs_full_refresh"]
