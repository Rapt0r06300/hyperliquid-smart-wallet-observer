from __future__ import annotations

from datetime import UTC, datetime, timedelta


def heartbeat_stale(last_seen: datetime | None, *, max_age_seconds: int) -> bool:
    if last_seen is None:
        return True
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return datetime.now(UTC) - last_seen > timedelta(seconds=max_age_seconds)
