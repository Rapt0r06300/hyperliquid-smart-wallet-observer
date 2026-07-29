"""Per-field freshness metadata for shared runtime status files."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

STATUS_FIELD_META_KEY = "status_field_meta"


def stamp_status_fields(
    payload: dict[str, Any],
    fields: Iterable[str],
    *,
    producer: str,
    session_id: str,
    updated_at_ms: int,
) -> None:
    meta = payload.get(STATUS_FIELD_META_KEY)
    if not isinstance(meta, dict):
        meta = {}
    for field in fields:
        meta[str(field)] = {
            "updated_at_ms": int(updated_at_ms),
            "producer": str(producer),
            "session_id": str(session_id),
        }
    payload[STATUS_FIELD_META_KEY] = meta


def status_field_is_fresh(
    payload: dict[str, Any],
    field: str,
    *,
    current_ms: int,
    session_id: str,
    max_age_ms: int,
) -> bool:
    meta = payload.get(STATUS_FIELD_META_KEY)
    if not isinstance(meta, dict):
        return False
    stamp = meta.get(str(field))
    if not isinstance(stamp, dict):
        return False
    try:
        updated_at_ms = int(stamp["updated_at_ms"])
    except (KeyError, TypeError, ValueError):
        return False
    stamped_session = str(stamp.get("session_id") or "")
    if session_id and stamped_session != session_id:
        return False
    age_ms = int(current_ms) - updated_at_ms
    return 0 <= age_ms <= max(0, int(max_age_ms))


__all__ = [
    "STATUS_FIELD_META_KEY",
    "stamp_status_fields",
    "status_field_is_fresh",
]
