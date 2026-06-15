from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc


@dataclass(frozen=True)
class ApiHealth:
    component: str
    ok: bool
    checked_at: datetime
    message: str
    read_only: bool = True


def healthy(component: str, message: str = "OK") -> ApiHealth:
    return ApiHealth(component=component, ok=True, checked_at=datetime.now(UTC), message=message)


def unhealthy(component: str, message: str) -> ApiHealth:
    return ApiHealth(component=component, ok=False, checked_at=datetime.now(UTC), message=message)
