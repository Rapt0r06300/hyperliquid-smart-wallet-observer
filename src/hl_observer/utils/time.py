from __future__ import annotations

import time
from datetime import UTC, datetime


def now_ms() -> int:
    return int(time.time() * 1000)


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def format_ms_as_clock(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%H:%M:%S")
