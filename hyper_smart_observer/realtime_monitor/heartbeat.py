from __future__ import annotations

from datetime import datetime, timedelta
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc


HEARTBEAT_INTERVAL_SECONDS = 30.0


def build_heartbeat_payload() -> dict[str, str]:
    """Construit l'unique heartbeat autorisé sur le canal WebSocket.

    Le runtime de recherche n'utilise jamais la méthode ``post`` du WebSocket,
    qui pourrait transporter des actions signées. Le heartbeat officiel est un
    simple ``{"method": "ping"}``.
    """

    return {"method": "ping"}


def heartbeat_stale(last_seen: datetime | None, *, max_age_seconds: int) -> bool:
    if last_seen is None:
        return True
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return datetime.now(UTC) - last_seen > timedelta(seconds=max_age_seconds)


__all__ = ["HEARTBEAT_INTERVAL_SECONDS", "build_heartbeat_payload", "heartbeat_stale"]
